"""NPA core: DCB Spec, Context, domain tree, descend/ascend.

Aligned with notes/SPEC_NPA_CORE.md v0.1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple

from .memory import Access, Region, View, parse_regions


class Lifecycle(Enum):
    FREE = "free"  # unused or reaped
    LIVE = "live"  # running / resumable
    TERM = "term"  # exited, not reaped yet


class Reason(Enum):
    SERVICE = 0x00
    RESULT = 0x01
    EXCEPTION = 0x02
    EXIT = 0x03


class MemFault(Exception):
    def __init__(self, kind: str, addr: int, detail: str = ""):
        self.kind = kind
        self.addr = addr
        self.detail = detail
        super().__init__(f"{kind} @0x{addr:x} {detail}")


class ProgEnd(Exception):
    """Program finished a domain episode (used by scenario drivers)."""


# --- DCB Spec Field (10 words / 40B) ---------------------------------

@dataclass
class DCB:
    sz: int = 10
    id: int = 0
    entry: int = 0
    edel: int = 0  # 1 = child may self-handle sync exceptions
    exc: int = 0
    irq: int = 0
    ipa: int = 0  # 0 = no constraint table; else addr of region table
    ptb: int = 0  # 0 = inherit translation
    child: int = 0  # current child DCB addr
    sec: int = 0
    # Impdef (not Spec)
    isa: int = 0

    # Software-side convenience for the model (NOT Spec fields):
    # region tables live in machine memory as word triples.
    _kind: str = "spec"  # marker


# --- Context (ISA-defined; we use a tiny synthetic ISA) ---------------

@dataclass
class Context:
    pc: int = 0
    sp: int = 0
    regs: List[int] = field(default_factory=lambda: [0] * 8)
    valid: bool = False  # False = first entry (use dcb.entry)

    def clone(self) -> "Context":
        return Context(pc=self.pc, sp=self.sp, regs=list(self.regs), valid=self.valid)


@dataclass
class Domain:
    dcb_addr: int
    dcb: DCB
    ctx: Context
    parent: Optional["Domain"] = None
    # resolved once per episode
    view: View = field(default_factory=lambda: View(inherit=True))
    lifecycle: Lifecycle = Lifecycle.FREE  # FREE / LIVE / TERM (I17/I18)

    @property
    def depth(self) -> int:
        d = 0
        p = self.parent
        while p is not None:
            d += 1
            p = p.parent
        return d

    def rel(self, n: int) -> Optional["Domain"]:
        """Relative view: n=0 self, n=1 child, n=-1 parent."""
        if n == 0:
            return self
        if n > 0:
            cur: Optional[Domain] = self
            for _ in range(n):
                if cur is None:
                    return None
                # only "current" child link
                child_addr = cur.dcb.child
                if not child_addr:
                    return None
                cur = cur._child_obj
            return cur
        cur = self
        for _ in range(-n):
            if cur is None or cur.parent is None:
                return None
            cur = cur.parent
        return cur

    # set by machine
    _child_obj: Optional["Domain"] = None


# --- Machine ---------------------------------------------------------

class NPAMachine:
    """Tiny interpreter sufficient to probe control/memory semantics."""

    def __init__(self, mem_size: int = 1 << 20):
        self.mem_size = mem_size
        self.memory: Dict[int, int] = {}  # word-addressed bytes packed simply
        self.dcb_mem: Dict[int, DCB] = {}  # dcb_addr -> DCB
        self.region_mem: Dict[int, List[Tuple[int, int, int]]] = {}
        self.root: Optional[Domain] = None
        self.current: Optional[Domain] = None
        self.log: List[str] = []
        # reason,x delivered to parent after ascend
        self.last_ascend: Optional[Tuple[Reason, Any]] = None
        self._cache: Dict[Any, Domain] = {}  # ("dom", dcb_addr) -> Domain

    # --- memory words ---
    def wload(self, addr: int) -> int:
        return self.memory.get(addr, 0)

    def wstore(self, addr: int, val: int) -> None:
        self.memory[addr] = val

    def write_regions(self, addr: int, entries: List[Tuple[int, int, int]]) -> None:
        self.region_mem[addr] = list(entries)

    def read_regions(self, addr: int) -> List[Tuple[int, int, int]]:
        return list(self.region_mem.get(addr, []))

    # --- root boot ---
    def boot_root(self, dcb_addr: int, dcb: DCB, ctx: Context) -> Domain:
        self.dcb_mem[dcb_addr] = dcb
        dom = Domain(dcb_addr=dcb_addr, dcb=dcb, ctx=ctx.clone(), parent=None)
        dom.ctx.valid = True
        dom.view = self._build_view(dom)
        self.root = dom
        self.current = dom
        self._link_child(dom)
        return dom

    def _build_view(self, dom: Domain) -> View:
        dcb = dom.dcb
        parent_view = dom.parent.view if dom.parent is not None else None
        if dcb.ptb == 0 and dcb.ipa == 0:
            # pure INHERIT: share parent's entire translation + permissions
            return View(inherit=True, allow=[], parent_view=parent_view)
        if dcb.ptb == 0 and dcb.ipa != 0:
            # INHERIT translation + permission overlay on VA
            # (MCU sandbox / JIT shared-PT)
            allow = parse_regions(self.read_regions(dcb.ipa))
            return View(inherit=True, allow=allow, parent_view=parent_view)
        # stacked: child VA -> parent-view address, then parent chains
        pt: Dict[int, int] = {}
        for va, pa, attr in self.read_regions(dcb.ptb):
            if va == 0 and pa == 0 and attr == 0:
                break  # terminator only when all-zero
            pt[va] = pa
        allow = parse_regions(self.read_regions(dcb.ipa)) if dcb.ipa else []
        return View(inherit=False, pt=pt, allow=allow, parent_view=parent_view)

    def _link_child(self, parent: Domain) -> None:
        if parent.dcb.child:
            child_dom = self._domain_for(parent.dcb.child, parent)
            parent._child_obj = child_dom
        else:
            parent._child_obj = None

    def _domain_for(self, dcb_addr: int, parent: Domain) -> Domain:
        if dcb_addr not in self.dcb_mem:
            raise KeyError(f"no DCB at 0x{dcb_addr:x}")
        dcb = self.dcb_mem[dcb_addr]
        key = ("dom", dcb_addr)
        if key not in self._cache:
            self._cache[key] = Domain(
                dcb_addr=dcb_addr,
                dcb=dcb,
                ctx=Context(),
                parent=parent,
                view=self._build_view_placeholder(dcb),
            )
        dom = self._cache[key]
        dom.parent = parent
        dom.dcb = dcb
        return dom

    def _build_view_placeholder(self, dcb: DCB) -> View:
        # rebuilt at descend
        return View(inherit=True)

    def install_dcb(self, addr: int, dcb: DCB) -> None:
        self.dcb_mem[addr] = dcb
        # fresh DCB object at addr = new domain (I17 reap/reuse)
        self._cache.pop(("dom", addr), None)

    # --- primitives (SPEC §3) ---------------------------------------

    def descend(self, dcb_addr: int) -> str:
        """Call/enter child. Parent suspends at call site (we return 'suspended')."""
        if self.current is None:
            raise RuntimeError("no current domain")
        parent = self.current
        if parent.dcb.child and parent.dcb.child != dcb_addr:
            # C1: only one current child link; software must re-point
            raise RuntimeError(
                f"I7/C1: parent already has child=0x{parent.dcb.child:x}, "
                f"cannot descend to 0x{dcb_addr:x} without software rebind"
            )

        if dcb_addr not in self.dcb_mem:
            raise RuntimeError(f"no DCB at 0x{dcb_addr:x}")
        dcb = self.dcb_mem[dcb_addr]

        # I7: child cannot have written parent-owned fields — model enforces
        # ownership at write helpers; here we just validate sz.
        if dcb.sz < 10:
            raise RuntimeError(f"sz too small: {dcb.sz}")

        first = dcb_addr not in self._cache or not self._cache[("dom", dcb_addr)].ctx.valid
        # normalize cache key
        key = ("dom", dcb_addr)
        if key not in self._cache:
            self._cache[key] = Domain(
                dcb_addr=dcb_addr,
                dcb=dcb,
                ctx=Context(),
                parent=parent,
            )
        child = self._cache[key]
        child.parent = parent
        child.dcb = dcb

        # I17/I18: lifecycle decides first vs resume vs reject
        if child.lifecycle == Lifecycle.TERM:
            raise RuntimeError(
                f"descend to TERM domain id={dcb.id} at 0x{dcb_addr:x}: "
                f"parent must reap/reinit DCB before reuse"
            )
        is_first = child.lifecycle == Lifecycle.FREE

        child.view = self._build_view(child)

        parent.dcb.child = dcb_addr
        parent._child_obj = child

        if is_first or not child.ctx.valid:
            # first entry: PC <- dcb.entry
            if dcb.entry == 0:
                raise RuntimeError("first descend requires entry != 0")
            child.ctx.pc = dcb.entry
            child.ctx.valid = True
            child.lifecycle = Lifecycle.LIVE
            self.log.append(f"descend first -> id={dcb.id} entry=0x{dcb.entry:x}")
        else:
            child.lifecycle = Lifecycle.LIVE
            self.log.append(f"descend resume -> id={dcb.id} pc=0x{child.ctx.pc:x}")

        # parent suspended at call site (driver models this via call stack)
        self.current = child
        return "suspended"

    def ascend(self, reason: Reason, x: Any = None) -> Tuple[Reason, Any]:
        """Return to parent's descend call site. Only upward primitive."""
        if self.current is None:
            raise RuntimeError("no current domain")
        if self.current.parent is None:
            raise RuntimeError("I1: ascend from root illegal")
        child = self.current
        parent = child.parent
        # save child context already held in child.ctx
        child.ctx.valid = True
        self.last_ascend = (reason, x)
        self.current = parent
        parent._child_obj = child  # keep link for later resume

        # EXIT: lifecycle FREE→TERM (I17); hardware clears parent.child
        if reason == Reason.EXIT:
            child.lifecycle = Lifecycle.TERM
            parent.dcb.child = 0
            parent._child_obj = None
            self.log.append(f"exit-term id={child.dcb.id} (parent reaps DCB)")

        self.log.append(f"ascend {reason.name} x={x!r} -> parent id={parent.dcb.id}")
        return reason, x

    def reap(self, parent: Domain, dcb_addr: int) -> None:
        """Parent duty: destroy/reinit child DCB after exit (TERM → FREE)."""
        key = ("dom", dcb_addr)
        if key in self._cache:
            del self._cache[key]
        if parent.dcb.child == dcb_addr:
            parent.dcb.child = 0
        if parent._child_obj is not None and parent._child_obj.dcb_addr == dcb_addr:
            parent._child_obj = None
        self.log.append(f"reap dcb=0x{dcb_addr:x} (lifecycle -> FREE)")


    # --- memory (SPEC §5) -------------------------------------------

    def _view(self) -> View:
        assert self.current is not None
        return self.current.view

    def load(self, va: int, acc: Access = Access.R, size: int = 4) -> int:
        v = self._view()
        try:
            name = va if v.inherit else v.translate_one(va)
            pa = v.translate(va)
        except KeyError:
            raise MemFault("translation", va, "unmapped VA")
        err = v.check(name, size, acc)
        if err:
            raise MemFault("permission", name, err)
        return self.wload(pa)

    def store(self, va: int, val: int, acc: Access = Access.W, size: int = 4) -> None:
        v = self._view()
        try:
            name = va if v.inherit else v.translate_one(va)
            pa = v.translate(va)
        except KeyError:
            raise MemFault("translation", va, "unmapped VA")
        err = v.check(name, size, acc)
        if err:
            raise MemFault("permission", name, err)
        self.wstore(pa, val)

    # --- exception route (SPEC §4/§7) -------------------------------

    def raise_exception(self, kind: str, addr: int = 0) -> None:
        """Sync exception in current domain (SPEC §7.1 edel/exc route)."""
        assert self.current is not None
        dcb = self.current.dcb
        if dcb.edel == 1 and dcb.exc != 0:
            self.log.append(f"exception local exc=0x{dcb.exc:x} kind={kind}")
            self.current.ctx.pc = dcb.exc
            raise ProgEnd(f"local-exc:{kind}")
        # I13: edel=0 or exc=0 → must ascend (never end locally)
        if self.current.parent is None:
            raise MemFault("unhandled-root-exc", addr, kind)
        self.ascend(Reason.EXCEPTION, {"kind": kind, "addr": addr})

    # --- DCB field write with ownership (I7) -------------------------

    PARENT_FIELDS = {"sz", "entry", "edel", "ipa", "child"}
    SYSTEM_FIELDS = {"id", "irq", "sec"}
    CHILD_FIELDS = {"exc", "ptb"}

    def dcb_write(self, who: str, dcb_addr: int, field: str, val: int) -> None:
        dcb = self.dcb_mem[dcb_addr]
        if who == "parent" and field not in self.PARENT_FIELDS | self.CHILD_FIELDS:
            # parent may initialize child-owned fields before first enter
            if field not in self.CHILD_FIELDS:
                raise RuntimeError(f"I7: parent cannot write {field}")
        if who == "child" and field not in self.CHILD_FIELDS:
            raise RuntimeError(f"I7: child cannot write {field}")
        if who == "system" and field not in self.SYSTEM_FIELDS:
            raise RuntimeError(f"I7: system cannot write {field}")
        setattr(dcb, field, val)

    def rebind_child(self, parent: Domain, child_dcb: int) -> None:
        """Software (parent) C1: set current child link."""
        parent.dcb.child = child_dcb
        parent._child_obj = None
        if child_dcb:
            self._link_child(parent)
