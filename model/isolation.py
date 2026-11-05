"""Access-isolation matrix for secure domains — strengthened memory model.

Enhancements over LazySecureMem:
  - key_set_region (security subsystem only)
  - PTE-like region flags: SEC (confidential), SHARE (explicit shared)
  - Access kinds: DATA_READ, DATA_WRITE, FETCH (instruction)
  - Viewers: owner, parent, peer, root, lower (child of owner)

Matrix (target = secure domain memory):
  viewer    | data R/W | fetch/exec
  owner     | yes      | yes
  parent    | no*      | no*
  peer      | no       | no
  lower     | no       | no
  root      | sec only | sec only
  * csec: parent also no; sec: parent no, root yes

Run: python -m model.isolation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, Optional, Set

from .memsec import MemRegion, Probe, SecuritySub, expect
from .memory import Access


class Kind(Enum):
    READ = auto()
    WRITE = auto()
    FETCH = auto()  # instruction fetch / execute


@dataclass
class PTE:
    """Page-table style region entry (logical)."""

    base: int
    size: int
    attr: Access  # R/W/X
    owner_id: int
    sec: bool = False      # secure/confidential content
    csec: bool = False     # even root cannot read unless shared
    share: bool = False    # explicit shared window (declassified page)

    def contains(self, addr: int, n: int = 1) -> bool:
        return self.base <= addr and addr + n <= self.base + self.size


class IsoMem:
    """Memory with security bits + key setting + access kinds."""

    def __init__(self, sec: SecuritySub):
        self.sec = sec
        self.data: Dict[int, int] = {}
        self.code: Dict[int, int] = {}
        self.ptes: list[PTE] = []
        # region_base -> key (set by security subsystem)
        self.region_key: Dict[int, int] = {}

    def pte(self, r: PTE) -> None:
        self.ptes.append(r)

    def key_set_region(self, base: int, key: int, by_sec: bool = True) -> None:
        """Security-subsystem interface (I24: not parent software)."""
        if not by_sec:
            raise PermissionError("key_set_region is security-subsystem only")
        self.region_key[base] = key

    def _find(self, addr: int, n: int = 1) -> Optional[PTE]:
        for p in self.ptes:
            if p.contains(addr, n):
                return p
        return None

    def _allow(self, p: PTE, viewer_id: int, kind: Kind) -> Optional[str]:
        """Return error string if denied."""
        # execute needs X
        if kind == Kind.FETCH and not (p.attr & Access.X):
            return "no X"
        if kind == Kind.READ and not (p.attr & Access.R):
            return "no R"
        if kind == Kind.WRITE and not (p.attr & Access.W):
            return "no W"

        if not p.sec:
            return None  # non-secure: only attr matters

        if p.share:
            return None  # declassified shared page

        if viewer_id == p.owner_id:
            return None

        # csec: nobody else, including root
        if p.csec:
            return "csec: owner-only (or share)"

        # ordinary sec: root trust only
        if viewer_id == 0:
            return None
        return "sec: root/owner only"

    def access(self, addr: int, viewer_id: int, kind: Kind, val: int = 0) -> int:
        p = self._find(addr)
        if p is None:
            raise MemFault(f"{kind.name}", addr, "unmapped")
        err = self._allow(p, viewer_id, kind)
        if err:
            raise MemFault("permission", addr, err)
        # key check for sec pages (engine path)
        if p.sec and not p.share:
            k = self.region_key.get(p.base)
            if p.csec and viewer_id != p.owner_id:
                raise MemFault("permission", addr, "csec key")
            if p.csec and k is None and viewer_id == p.owner_id:
                # owner still needs key issued
                if p.base not in self.region_key:
                    raise MemFault("permission", addr, "no key")
        if kind == Kind.WRITE:
            self.data[addr] = val
            return val
        if kind == Kind.FETCH:
            return self.code.get(addr, 0)
        return self.data.get(addr, 0)


# MemFault from core — import late to avoid cycle in docs
from .core import MemFault  # noqa: E402


def _setup_csec(sec_id: int = 10) -> tuple:
    sec = SecuritySub()
    sec.preset_load(sec_id, {"conf": True, "sec": True})
    sec.bind(sec_id, root_ok=True)
    mem = IsoMem(sec)
    # code + data for secure domain
    mem.pte(PTE(0x2000, 0x1000, Access.RX, owner_id=sec_id, sec=True, csec=True))
    mem.pte(PTE(0x3000, 0x1000, Access.RW, owner_id=sec_id, sec=True, csec=True))
    mem.key_set_region(0x2000, 0x1001, by_sec=True)
    mem.key_set_region(0x3000, 0x1002, by_sec=True)
    mem.code[0x2000] = 0xAA  # "instruction"
    mem.data[0x3000] = 0xBB  # "data"
    return sec, mem, sec_id


def _setup_sec_ordinary(sec_id: int = 20) -> tuple:
    sec = SecuritySub()
    sec.preset_load(sec_id, {"sec": True})
    sec.bind(sec_id, root_ok=True)
    mem = IsoMem(sec)
    mem.pte(PTE(0x4000, 0x100, Access.RW, owner_id=sec_id, sec=True, csec=False))
    mem.key_set_region(0x4000, 0x2001, by_sec=True)
    mem.data[0x4000] = 0xCC
    return sec, mem, sec_id


def t_matrix_data_and_fetch() -> None:
    """Full matrix: viewer x {read, write, fetch} on csec pages."""
    _, mem, sid = _setup_csec()
    viewers = {
        "owner": sid,
        "parent": 5,      # non-root parent
        "peer": 21,       # sibling domain id
        "lower": 99,      # deeper / less privileged
        "root": 0,
    }
    # expected allow?
    # owner: all; parent/peer/lower/root: none on csec
    for name, vid in viewers.items():
        for kind, addr, wval in (
            (Kind.READ, 0x3000, 0),
            (Kind.WRITE, 0x3000, 1),
            (Kind.FETCH, 0x2000, 0),
        ):
            ok = name == "owner"
            try:
                mem.access(addr, vid, kind, wval)
                got = True
            except MemFault:
                got = False
            expect(got == ok, f"csec {name} {kind.name} @ {addr:#x}: got {got} want {ok}")


def t_sec_ordinary_root_vs_parent() -> None:
    _, mem, sid = _setup_sec_ordinary()
    expect(mem.access(0x4000, 0, Kind.READ) == 0xCC, "root reads ordinary sec")
    try:
        mem.access(0x4000, 5, Kind.READ)
        raise Probe("parent read ordinary sec")
    except MemFault:
        pass
    try:
        mem.access(0x4000, 21, Kind.WRITE, 1)
        raise Probe("peer write ordinary sec")
    except MemFault:
        pass


def t_parent_cannot_snoop_csec() -> None:
    """Parent domain access confidential domain content — must fail."""
    _, mem, sid = _setup_csec()
    for addr, kind in ((0x3000, Kind.READ), (0x3000, Kind.WRITE), (0x2000, Kind.FETCH)):
        try:
            mem.access(addr, 5, kind, 0)
            raise Probe(f"parent {kind.name} csec")
        except MemFault:
            pass
    # even with "parent knows PA" and data present
    expect(mem.data.get(0x3000) == 0xBB, "data still in engine")


def t_share_window_only_page() -> None:
    sec, mem, sid = _setup_csec()
    # mark data page shared (declassify)
    for p in mem.ptes:
        if p.base == 0x3000:
            p.share = True
    expect(mem.access(0x3000, 5, Kind.READ) == 0xBB, "parent reads shared page")
    # code page still closed
    try:
        mem.access(0x2000, 5, Kind.FETCH)
        raise Probe("parent fetch after share data only")
    except MemFault:
        pass


def t_key_interface_security_only() -> None:
    mem = IsoMem(SecuritySub())
    mem.pte(PTE(0x5000, 0x10, Access.RW, owner_id=1, sec=True, csec=True))
    try:
        mem.key_set_region(0x5000, 1, by_sec=False)
        raise Probe("parent set key")
    except PermissionError:
        pass
    mem.key_set_region(0x5000, 1, by_sec=True)
    expect(mem.region_key[0x5000] == 1, "sec subsystem set key")


def t_fetch_needs_x() -> None:
    _, mem, sid = _setup_csec()
    # data page has no X
    try:
        mem.access(0x3000, sid, Kind.FETCH)
        raise Probe("fetch from non-X page")
    except MemFault:
        pass


def t_lower_domain_cannot_reach() -> None:
    """δ=+1 / lower cannot touch parent's secure content."""
    _, mem, sid = _setup_csec()
    child_id = sid + 1000
    try:
        mem.access(0x3000, child_id, Kind.READ)
        raise Probe("lower read csec")
    except MemFault:
        pass
    try:
        mem.access(0x2000, child_id, Kind.FETCH)
        raise Probe("lower fetch csec")
    except MemFault:
        pass


def t_peer_sibling_isolation() -> None:
    _, mem, sid = _setup_csec()
    peer = 77
    try:
        mem.access(0x3000, peer, Kind.READ)
        raise Probe("peer read")
    except MemFault:
        pass
    # peer's own memory is fine
    mem.pte(PTE(0x6000, 0x10, Access.RW, owner_id=peer, sec=False))
    mem.access(0x6000, peer, Kind.WRITE, 1)
    expect(mem.access(0x6000, peer, Kind.READ) == 1, "peer own data")


def t_control_not_visibility() -> None:
    """I27: parent may preempt/interrupt csec; must not see content."""
    from .core import DCB, Context, Lifecycle, NPAMachine, Reason

    _, mem, sid = _setup_csec()
    m = NPAMachine()
    root = DCB(id=0, entry=0x1000, ptb=0, ipa=0)
    m.boot_root(0x8000, root, Context(pc=0x1000, valid=True))
    csec = DCB(id=sid, entry=0x2000, ptb=0, ipa=0, edel=0)
    m.install_dcb(0x8100, csec)
    m.descend(0x8100)
    expect(m.current.dcb.id == sid, "in csec")

    # high-priority interrupt / preempt: ascend back to parent control
    r, x = m.ascend(Reason.SERVICE, "irq-preempt")
    expect(m.current.dcb.id == 0, "parent regained control")
    # parent can read DCB config (privilege state) but not csec content
    expect(m.current.dcb.child == 0x8100 or m.root.dcb.child == 0x8100, "still linked")
    try:
        mem.access(0x3000, 0, Kind.READ)
        raise Probe("parent saw csec content after preempt")
    except MemFault:
        pass
    # parent resumes domain
    m.descend(0x8100)
    expect(m.current.dcb.id == sid, "resumed csec")
    # owner still reads
    expect(mem.access(0x3000, sid, Kind.READ) == 0xBB, "owner data intact")
    m.ascend(Reason.EXIT, None)
    m.reap(m.root, 0x8100)
    expect(m.root.dcb.child == 0, "reaped")


class MaskedContext:
    """Security-subsystem disguise for parent-visible context (I28)."""

    def __init__(self) -> None:
        self._true_ctx: Dict[int, Dict] = {}
        self._token: Dict[int, int] = {}
        self._next = 1

    def park_true(self, domain_id: int, pc: int, regs: Dict[int, int]) -> int:
        self._true_ctx[domain_id] = {"pc": pc, "regs": dict(regs)}
        tok = self._next
        self._next += 1
        self._token[domain_id] = tok
        return tok

    def parent_view(self, domain_id: int) -> dict:
        return {
            "token": self._token.get(domain_id),
            "pc": None,
            "regs": None,
            "note": "opaque; security restores on resume",
        }

    def resume_true(self, domain_id: int, token: int) -> dict:
        if self._token.get(domain_id) != token:
            raise PermissionError("bad token")
        return self._true_ctx[domain_id]

    def revoke(self, domain_id: int) -> None:
        self._true_ctx.pop(domain_id, None)
        self._token.pop(domain_id, None)


def t_masked_context_on_preempt() -> None:
    """I28: parent gets disguise; security unwraps on resume."""
    mask = MaskedContext()
    sid = 10
    real_pc, real_regs = 0x2ABC, {0: 0xDEAD, 1: 0xBEEF}
    tok = mask.park_true(sid, real_pc, real_regs)

    view = mask.parent_view(sid)
    expect(view["token"] == tok, "token issued")
    expect(view["pc"] is None and view["regs"] is None, "parent sees no true ctx")

    true = mask.resume_true(sid, tok)
    expect(true["pc"] == real_pc and true["regs"][0] == 0xDEAD, "restore true")
    try:
        mask.resume_true(sid, tok + 99)
        raise Probe("bad token accepted")
    except PermissionError:
        pass

    mask.revoke(sid)
    try:
        mask.resume_true(sid, tok)
        raise Probe("token works after revoke")
    except PermissionError:
        pass


def main() -> None:
    cases = [
        ("matrix data/fetch x owner/parent/peer/lower/root", t_matrix_data_and_fetch),
        ("ordinary sec root vs parent/peer", t_sec_ordinary_root_vs_parent),
        ("parent cannot snoop csec", t_parent_cannot_snoop_csec),
        ("share window only that page", t_share_window_only_page),
        ("key_set_region security-only", t_key_interface_security_only),
        ("fetch requires X", t_fetch_needs_x),
        ("lower domain cannot reach", t_lower_domain_cannot_reach),
        ("peer sibling isolation", t_peer_sibling_isolation),
        ("preempt ok, content hidden (I27)", t_control_not_visibility),
        ("masked context park/resume (I28)", t_masked_context_on_preempt),
    ]
    for name, fn in cases:
        try:
            fn()
            print(f"OK  {name}")
        except Probe as e:
            print(f"PROBE  {name}: {e}")
        except Exception as e:
            print(f"FAIL  {name}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
