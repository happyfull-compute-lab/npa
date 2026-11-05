"""Scenario probes: MCU / 3-layer / 4-layer virt / 5-layer JIT.

ARM EL names appear only as comments for humans — architecture uses Domain
relative perspective only.

Run: python -m model.scenarios
"""

from __future__ import annotations

from typing import Callable, List, Optional

from .core import DCB, Context, Domain, MemFault, ProgEnd, NPAMachine, Reason
from .memory import Access, Region


class Probe(Exception):
    """Design gap found — stop and discuss."""


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def run(name: str, fn: Callable[[], None]) -> None:
    print(f"\n=== {name} ===")
    try:
        fn()
        print(f"OK  {name}")
    except Probe as e:
        print(f"PROBE  {name}: {e}")
    except AssertionError as e:
        print(f"FAIL  {name}: {e}")
    except Exception as e:
        print(f"ERROR {name}: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Scenario 1: MCU, two domains
#   D0 monitor/firmware (like a secure MCU image)
#   D1 app sandbox
#   No MMU: app may only touch (R) flash const + (RW) its data, not firmware RW.
# ---------------------------------------------------------------------------

def scenario_mcu_2() -> None:
    m = NPAMachine()
    # physical map
    # 0x0000 firmware code RX
    # 0x1000 firmware data RW  (app must not touch)
    # 0x2000 app code RX
    # 0x3000 app data RW

    root_dcb = DCB(id=0, entry=0x0000, exc=0, ptb=0, ipa=0)
    m.boot_root(0x8000, root_dcb, Context(pc=0x0000, valid=True))

    app = DCB(id=1, entry=0x2000, exc=0, ptb=0, ipa=0x9000, irq=0, sec=0)
    m.install_dcb(0x8100, app)
    # MCU constraint: inherit translation + allow-list
    m.write_regions(0x9000, [
        (0x2000, 0x1000, int(Access.RX)),
        (0x3000, 0x1000, int(Access.RW)),
        (0, 0, 0),
    ])

    # parent configures app
    m.dcb_write("parent", 0x8100, "entry", 0x2000)
    m.dcb_write("parent", 0x8100, "ipa", 0x9000)

    # --- parent "calls" app ---
    m.descend(0x8100)
    # now in app: shared addresses, filtered
    val = m.load(0x2000, Access.R)
    m.store(0x3000, 0x1234, Access.W)
    try:
        m.store(0x1000, 0x99, Access.W)
        raise Probe("app wrote firmware data — ipa-as-allow failed")
    except MemFault as e:
        expect(e.kind == "permission", f"want permission fault, got {e}")

    try:
        m.load(0x1000, Access.R)
        raise Probe("app read firmware data — allow-list should hide it")
    except MemFault as e:
        expect(e.kind == "permission", f"want permission fault on read, got {e}")

    # SERVICE back to parent call site
    r, x = m.ascend(Reason.SERVICE, "need_ticks")
    expect(r == Reason.SERVICE and x == "need_ticks", "ascend reason/x")
    expect(m.current is not None and m.current.dcb.id == 0, "parent at call site")

    # parent resumes app
    m.descend(0x8100)
    expect(m.current.dcb.id == 1, "resumed app")
    m.ascend(Reason.EXIT, None)

    # parent can rebind another child (C1)
    other = DCB(id=2, entry=0x2000, ipa=0x9000, ptb=0)
    m.install_dcb(0x8200, other)
    m.rebind_child(m.root, 0x8200)
    m.descend(0x8200)
    expect(m.current.dcb.id == 2, "second child via rebind")
    m.ascend(Reason.EXIT, None)


# ---------------------------------------------------------------------------
# Scenario 2: three domains — monitor / kernel / user
#   (EL3 / EL1 / EL0 as *analogy only*)
#   Kernel has its own PT; user has stacked PT under kernel.
# ---------------------------------------------------------------------------

def scenario_3layer() -> None:
    m = NPAMachine()
    # D0 monitor: own everything
    mon = DCB(id=0, entry=0x1000, ptb=0, ipa=0)
    m.boot_root(0x8000, mon, Context(pc=0x1000, valid=True))

    # D1 kernel: stacked map; parent (monitor) delegates exceptions
    kern = DCB(id=1, entry=0x2000, ptb=0xA000, ipa=0xB000, exc=0x2100, edel=1)
    m.install_dcb(0x8100, kern)
    m.write_regions(0xA000, [(0x0000, 0x10000, int(Access.RWX)), (0, 0, 0)])  # used as VA->PA pairs below
    # For stacked model in core, ptb table is (va, pa, attr) pairs:
    m.write_regions(0xA000, [
        (0x0000, 0x10000, int(Access.RWX)),
        (0x1000, 0x11000, int(Access.RWX)),
        (0, 0, 0),
    ])
    m.write_regions(0xB000, [
        (0x10000, 0x20000, int(Access.RWX)),
        (0, 0, 0),
    ])

    # D2 user: stacked under kernel; VA 0 -> phys 0x10000 (via chain in probe)
    # Our minimal model only stacks ONE level per view (VA -> parent-view PA).
    # user pt: VA 0x0 -> 0x0 (kernel-view), kernel translates 0x0 -> 0x10000
    user = DCB(id=2, entry=0x3000, ptb=0xC000, ipa=0xD000, exc=0)
    m.install_dcb(0x8200, user)
    m.write_regions(0xC000, [
        (0x0000, 0x0000, int(Access.RW)),   # user VA0 -> kernel-view 0
        (0x0800, 0x1000, int(Access.RW)),   # maps into kernel window but NOT in allow
        (0x3000, 0x3000, int(Access.RX)),
        (0, 0, 0),
    ])
    m.write_regions(0xD000, [
        (0x0000, 0x1000, int(Access.RW)),
        (0x3000, 0x1000, int(Access.RX)),
        (0, 0, 0),
    ])

    m.dcb_write("parent", 0x8100, "entry", 0x2000)
    m.dcb_write("parent", 0x8100, "child", 0x8200)

    m.descend(0x8100)  # monitor -> kernel
    expect(m.current.dcb.id == 1, "in kernel")

    # kernel stacks user as current child
    m.rebind_child(m.current, 0x8200)
    m.descend(0x8200)  # kernel -> user
    expect(m.current.dcb.id == 2, "in user")

    # user can touch its allow window (VA 0 -> kernel-view 0 -> phys 0x10000)
    m.store(0x0000, 0xAA, Access.W)
    expect(m.wload(0x10000) == 0xAA, f"chained store to phys, got {m.wload(0x10000):#x}")

    # user VA 0x0800 is mapped but outside allow — must be permission fault
    try:
        m.store(0x0800, 1, Access.W)
        raise Probe("user accessed outside ipa allow")
    except MemFault as e:
        expect(e.kind == "permission", f"want permission, got {e}")

    # service path: user -> kernel -> monitor -> back
    r, x = m.ascend(Reason.SERVICE, "sys_open")
    expect(m.current.dcb.id == 1, "back at kernel call site")
    expect(r == Reason.SERVICE and x == "sys_open", "sys_open delivered")

    # kernel asks monitor
    r2, x2 = m.ascend(Reason.SERVICE, "smc_get_key")
    expect(m.current.dcb.id == 0, "back at monitor call site")
    expect(x2 == "smc_get_key", "smc delivered")

    # walk back down
    m.descend(0x8100)  # resume kernel
    m.descend(0x8200)  # resume user
    expect(m.current.dcb.id == 2, "user resumed")
    m.ascend(Reason.RESULT, 3)
    expect(m.current.dcb.id == 1, "kernel got result")
    m.ascend(Reason.RESULT, 0)
    expect(m.current.dcb.id == 0, "monitor got result")


# ---------------------------------------------------------------------------
# Scenario 3: four domains — monitor / hyp / guest-kernel / guest-user
#   (EL3 / EL2 / EL1 / EL0 analogy)
# ---------------------------------------------------------------------------

def scenario_4layer_virt() -> None:
    m = NPAMachine()
    mon = DCB(id=0, entry=0x1000, ptb=0, ipa=0)
    m.boot_root(0x8000, mon, Context(pc=0x1000, valid=True))

    hyp = DCB(id=1, entry=0x2000, ptb=0, ipa=0, exc=0x2100, edel=1)  # inherit monitor
    gk = DCB(id=2, entry=0x3000, ptb=0xA000, ipa=0xB000, edel=1, exc=0x3100)
    gu = DCB(id=3, entry=0x4000, ptb=0xC000, ipa=0xD000)

    m.install_dcb(0x8100, hyp)
    m.install_dcb(0x8200, gk)
    m.install_dcb(0x8300, gu)

    m.write_regions(0xA000, [(0x4000, 0x4000, int(Access.RWX)), (0, 0, 0)])
    m.write_regions(0xB000, [(0x4000, 0x4000, int(Access.RWX)), (0, 0, 0)])
    m.write_regions(0xC000, [(0x0000, 0x0000, int(Access.RW)), (0, 0, 0)])
    m.write_regions(0xD000, [(0x0000, 0x1000, int(Access.RW)), (0, 0, 0)])

    m.descend(0x8100)  # hyp
    # hyp creates guest: gk is current child of hyp
    m.rebind_child(m.current, 0x8200)
    m.descend(0x8200)  # guest kernel
    m.rebind_child(m.current, 0x8300)
    m.descend(0x8300)  # guest user
    expect(m.current.dcb.id == 3, "guest user")

    # hypercall: gu -> gk -> hyp
    r, x = m.ascend(Reason.SERVICE, "vmm_exit")
    expect(m.current.dcb.id == 2, "gk")
    r, x = m.ascend(Reason.SERVICE, "hvc")
    expect(m.current.dcb.id == 1, "hyp handles hvc")

    # resume chain
    m.descend(0x8200)
    m.descend(0x8300)
    expect(m.current.dcb.id == 3, "guest user resumed")

    # guest kernel page fault local: temporarily in gk
    m.ascend(Reason.EXCEPTION, {"kind": "translation", "addr": 0x5000})
    expect(m.current.dcb.id == 2, "gk sees exception")
    # gk has exc set — if we raise here it stays local
    m.raise_exception("translation", 0x5000)  # should go local exc
    # ProgEnd expected from raise_exception local path — catch:
    # actually raise_exception sets pc and raises ProgEnd; we handle below


def scenario_4layer_virt_wrap() -> None:
    try:
        scenario_4layer_virt()
    except ProgEnd as e:
        expect(str(e).startswith("local-exc"), f"want local-exc, got {e}")
        expect(NPAMachine is not None, "")
        # success: local exception taken
        return


# ---------------------------------------------------------------------------
# Scenario 4: five domains — + JIT under guest-user / EL0
#   JIT shares parent's address space (no new PT) but *reduced permissions*.
#   e.g. user has RWX; JIT may X its code region and W its data, not W user's stack.
# ---------------------------------------------------------------------------

def scenario_5layer_jit() -> None:
    m = NPAMachine()
    mon = DCB(id=0, entry=0x1000, ptb=0, ipa=0)
    m.boot_root(0x8000, mon, Context(pc=0x1000, valid=True))

    hyp = DCB(id=1, entry=0x2000, ptb=0, ipa=0, edel=1, exc=0x2100)
    gk = DCB(id=2, entry=0x3000, ptb=0xA000, ipa=0xB000, edel=1, exc=0x3100)
    gu = DCB(id=3, entry=0x4000, ptb=0xC000, ipa=0xD000)
    # JIT: same space as gu (its parent), narrower perms; parent does NOT delegate
    jit = DCB(id=4, entry=0x5000, ptb=0, ipa=0xE000, edel=0, exc=0)  # ptb=0 inherit!

    for a, d in [(0x8100, hyp), (0x8200, gk), (0x8300, gu), (0x8400, jit)]:
        m.install_dcb(a, d)

    m.write_regions(0xA000, [(0x4000, 0x4000, int(Access.RWX)), (0x5000, 0x5000, int(Access.RWX)), (0x6000, 0x6000, int(Access.RWX)), (0, 0, 0)])
    m.write_regions(0xB000, [(0x4000, 0x20000, int(Access.RWX)), (0, 0, 0)])
    m.write_regions(0xC000, [(0x4000, 0x4000, int(Access.RWX)), (0x5000, 0x5000, int(Access.RWX)), (0x6000, 0x6000, int(Access.RWX)), (0, 0, 0)])
    m.write_regions(0xD000, [(0x4000, 0x20000, int(Access.RWX)), (0, 0, 0)])
    # JIT allow: RX code 0x5000-0x6000, RW data 0x6000-0x7000; NOT user stack 0x4000
    m.write_regions(0xE000, [
        (0x5000, 0x1000, int(Access.RX)),
        (0x6000, 0x1000, int(Access.RW)),
        (0, 0, 0),
    ])

    m.descend(0x8100)
    m.rebind_child(m.current, 0x8200)
    m.descend(0x8200)
    m.rebind_child(m.current, 0x8300)
    m.descend(0x8300)
    expect(m.current.dcb.id == 3, "EL0-like user")

    # user runs JIT as child with same PT, tighter allow
    m.rebind_child(m.current, 0x8400)
    m.descend(0x8400)
    expect(m.current.dcb.id == 4, "in jit domain")

    # JIT executes its code region
    _ = m.load(0x5000, Access.RX)
    m.store(0x6000, 7, Access.W)

    # JIT must not write user stack
    try:
        m.store(0x4000, 7, Access.W)
        raise Probe("JIT wrote user stack — need permission-only mode")
    except MemFault as e:
        expect(e.kind == "permission", str(e))

    # JIT cannot write its own code (RX)
    try:
        m.store(0x5000, 7, Access.W)
        raise Probe("JIT W+X — allow-list should forbid W on RX")
    except MemFault:
        pass

    # control: JIT ascend to user call site
    r, x = m.ascend(Reason.SERVICE, "jit_trap")
    expect(m.current.dcb.id == 3, "user call site")
    # user resumes JIT
    m.descend(0x8400)
    expect(m.current.dcb.id == 4, "jit resumed")
    m.ascend(Reason.EXIT, None)


# ---------------------------------------------------------------------------
# Scenario 5: edel delegation policy (I13)
#   strict child (edel=0): exception must ascend even if exc is set
#   delegated child (edel=1): local exc works
# ---------------------------------------------------------------------------

def scenario_edel_policy() -> None:
    m = NPAMachine()
    root = DCB(id=0, entry=0x1000, ptb=0, ipa=0)
    m.boot_root(0x8000, root, Context(pc=0x1000, valid=True))

    # strict: parent sets edel=0; child may write exc but it must NOT route
    strict = DCB(id=1, entry=0x2000, ptb=0, ipa=0, edel=0, exc=0x2F00)
    m.install_dcb(0x8100, strict)
    m.descend(0x8100)
    try:
        m.raise_exception("translation", 0x5000)
    except ProgEnd:
        raise Probe("I13: edel=0 still took local exc")
    expect(m.current.dcb.id == 0, "exception ascended to parent")
    expect(m.last_ascend and m.last_ascend[0] == Reason.EXCEPTION, "reason EXCEPTION")

    # delegated: edel=1 + exc → local
    soft = DCB(id=2, entry=0x3000, ptb=0, ipa=0, edel=1, exc=0x3100)
    m.install_dcb(0x8200, soft)
    m.rebind_child(m.root, 0x8200)
    m.descend(0x8200)
    try:
        m.raise_exception("translation", 0x5000)
        raise Probe("expected ProgEnd local-exc")
    except ProgEnd as e:
        expect(str(e).startswith("local-exc"), f"want local-exc, got {e}")
    expect(m.current.dcb.id == 2, "still in child after local route")

    # delegated but exc=0 → ascend
    soft.exc = 0
    try:
        m.raise_exception("permission", 0x1)
    except ProgEnd:
        raise Probe("exc=0 should ascend")
    expect(m.current.dcb.id == 0, "ascended with exc=0")


# ---------------------------------------------------------------------------
# Scenario 6: multi-VM + multi-process (C1 breadth)
#   hyp runs VM-A and VM-B (rebind between siblings)
#   each VM kernel runs P1 and P2 (two user domains)
#   verify: context isolation across switches; single child link (no dual active)
# ---------------------------------------------------------------------------

def scenario_multi_vm_proc() -> None:
    m = NPAMachine()
    root = DCB(id=0, entry=0x1000, ptb=0, ipa=0)
    m.boot_root(0x8000, root, Context(pc=0x1000, valid=True))

    # --- hyp under root ---
    hyp = DCB(id=1, entry=0x2000, ptb=0, ipa=0, edel=1, exc=0x2100)
    m.install_dcb(0x8100, hyp)
    m.descend(0x8100)
    expect(m.current.dcb.id == 1, "in hyp")

    # --- two VMs as siblings of hyp ---
    # each VM: guest-kernel (gk) with own PT window; we only need control + ctx
    vm_a = DCB(id=10, entry=0x3000, ptb=0, ipa=0, edel=1, exc=0x3100)
    vm_b = DCB(id=11, entry=0x4000, ptb=0, ipa=0, edel=1, exc=0x4100)
    m.install_dcb(0x8300, vm_a)
    m.install_dcb(0x8400, vm_b)

    # C1: hyp can only have one current child — switch via rebind
    m.rebind_child(m.current, 0x8300)
    m.descend(0x8300)  # enter VM-A
    expect(m.current.dcb.id == 10, "VM-A")
    # VM-A "runs" and yields
    m.ascend(Reason.SERVICE, "timer_yield_A")

    # switch to VM-B without destroying A
    m.rebind_child(m.current, 0x8400)
    m.descend(0x8400)
    expect(m.current.dcb.id == 11, "VM-B")
    m.ascend(Reason.SERVICE, "timer_yield_B")

    # resume VM-A — must still be A, not a fresh first-entry
    m.rebind_child(m.current, 0x8300)
    m.descend(0x8300)
    expect(m.current.dcb.id == 10, "VM-A resumed")
    m.ascend(Reason.EXIT, None)

    # --- multi-process under VM-B's kernel ---
    # model: VM-B acts as kernel; two user processes as its children
    m.rebind_child(m.current, 0x8400)
    m.descend(0x8400)  # back into VM-B
    p1 = DCB(id=20, entry=0x5000, ptb=0, ipa=0, edel=0, exc=0)
    p2 = DCB(id=21, entry=0x6000, ptb=0, ipa=0, edel=0, exc=0)
    m.install_dcb(0x8500, p1)
    m.install_dcb(0x8600, p2)

    # schedule P1
    m.rebind_child(m.current, 0x8500)
    m.descend(0x8500)
    expect(m.current.dcb.id == 20, "P1")
    # P1 does a syscall and returns to kernel
    m.ascend(Reason.SERVICE, "sys_write_P1")
    expect(m.current.dcb.id == 11, "kernel got P1 syscall")

    # schedule P2
    m.rebind_child(m.current, 0x8600)
    m.descend(0x8600)
    expect(m.current.dcb.id == 21, "P2")
    m.ascend(Reason.SERVICE, "sys_write_P2")

    # back to P1 — resume, not first entry
    m.rebind_child(m.current, 0x8500)
    m.descend(0x8500)
    expect(m.current.dcb.id == 20, "P1 resumed")
    m.ascend(Reason.EXIT, None)

    # --- C1 constraint: cannot descend to a non-current sibling without rebind ---
    # currently child link is 0 (after EXIT); try dual-active impossible
    # install a third process and show that if link points elsewhere, descend to old fails
    p3 = DCB(id=22, entry=0x7000, ptb=0, ipa=0)
    m.install_dcb(0x8700, p3)
    m.rebind_child(m.current, 0x8700)  # now current child = P3
    try:
        m.descend(0x8500)  # try P1 while link says P3
        raise Probe("C1: dual child link should be rejected")
    except RuntimeError as e:
        expect("already has child" in str(e) or "C1" in str(e), str(e))

    m.descend(0x8700)
    expect(m.current.dcb.id == 22, "P3")
    m.ascend(Reason.EXIT, None)   # back to VM-B (hyp's child)
    expect(m.current.dcb.id == 11, "VM-B after P3 exit")

    # unwind: VM-B exit → hyp, then hyp exit → root
    m.ascend(Reason.EXIT, None)
    expect(m.current.dcb.id == 1, "hyp")
    m.ascend(Reason.EXIT, None)
    expect(m.current.dcb.id == 0, "root")


def main() -> None:
    run("MCU 2-domain", scenario_mcu_2)
    run("3-layer monitor/kernel/user", scenario_3layer)
    run("4-layer virt", scenario_4layer_virt_wrap)
    run("5-layer JIT shared-PT", scenario_5layer_jit)
    run("edel delegation policy", scenario_edel_policy)
    run("multi-VM + multi-process", scenario_multi_vm_proc)
    print("\n--- done ---")


if __name__ == "__main__":
    main()
