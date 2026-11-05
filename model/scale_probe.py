"""Scale probe: many VMs / processes — surface implementation limits.

Run: python -m model.scale_probe
Not part of the four-scenario golden path; used to find scale bugs.
"""

from __future__ import annotations

from typing import List

from .core import DCB, Context, MemFault, ProgEnd, NPAMachine, Reason
from .memory import Access


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


class Probe(Exception):
    pass


def probe_many_processes(n_proc: int = 32) -> dict:
    """One kernel (hyp-like) with n_proc user domains; round-robin yield."""
    m = NPAMachine()
    root = DCB(id=0, entry=0x1000, ptb=0, ipa=0)
    m.boot_root(0x8000, root, Context(pc=0x1000, valid=True))

    kern = DCB(id=1, entry=0x2000, ptb=0, ipa=0, edel=1, exc=0x2100)
    m.install_dcb(0x8100, kern)
    m.descend(0x8100)

    procs: List[int] = []
    for i in range(n_proc):
        addr = 0x9000 + i * 0x100
        entry = 0x3000 + i * 0x10
        d = DCB(id=100 + i, entry=entry, ptb=0, ipa=0, edel=0, exc=0)
        m.install_dcb(addr, d)
        procs.append(addr)

    # round 1: first entry each, yield
    for i, addr in enumerate(procs):
        m.rebind_child(m.current, addr)
        m.descend(addr)
        expect(m.current.dcb.id == 100 + i, f"enter P{i}")
        r, x = m.ascend(Reason.SERVICE, f"yield-{i}")
        expect(m.current.dcb.id == 1, f"kernel after P{i}")
        expect(x == f"yield-{i}", f"arg P{i}")

    # round 2: resume each — must not look like first entry
    for i, addr in enumerate(procs):
        m.rebind_child(m.current, addr)
        m.descend(addr)
        expect(m.current.dcb.id == 100 + i, f"resume P{i}")
        m.ascend(Reason.RESULT, i)

    # round 3: fork-like — child of a process? process creates a thread domain
    # under P0 (nested width)
    m.rebind_child(m.current, procs[0])
    m.descend(procs[0])
    thr = DCB(id=200, entry=0x8000, ptb=0, ipa=0)
    m.install_dcb(0xA000, thr)
    m.rebind_child(m.current, 0xA000)
    m.descend(0xA000)
    expect(m.current.dcb.id == 200, "thread under P0")
    m.ascend(Reason.EXIT, None)
    m.ascend(Reason.EXIT, None)

    return {"n_proc": n_proc, "descend": m.log.count("descend"), "ascend": sum(1 for e in m.log if e.startswith("ascend"))}


def probe_many_vms(n_vm: int = 8, n_proc_each: int = 4) -> dict:
    """Hyp with n_vm VMs; each VM has n_proc_each processes."""
    m = NPAMachine()
    root = DCB(id=0, entry=0x1000, ptb=0, ipa=0)
    m.boot_root(0x8000, root, Context(pc=0x1000, valid=True))
    hyp = DCB(id=1, entry=0x2000, ptb=0, ipa=0, edel=1, exc=0x2100)
    m.install_dcb(0x8100, hyp)
    m.descend(0x8100)

    switches = 0
    for v in range(n_vm):
        vm_addr = 0x20000 + v * 0x1000
        vm = DCB(id=10 + v, entry=0x3000 + v, ptb=0, ipa=0, edel=1, exc=0x3100)
        m.install_dcb(vm_addr, vm)
        m.rebind_child(m.current, vm_addr)
        m.descend(vm_addr)
        switches += 1

        for p in range(n_proc_each):
            p_addr = 0x40000 + v * 0x1000 + p * 0x100
            proc = DCB(id=1000 + v * 16 + p, entry=0x5000 + p, ptb=0, ipa=0, edel=0)
            m.install_dcb(p_addr, proc)
            m.rebind_child(m.current, p_addr)
            m.descend(p_addr)
            switches += 1
            m.ascend(Reason.SERVICE, f"vm{v}-p{p}")
            expect(m.current.dcb.id == 10 + v, f"vm{v} after p{p}")
            # resume once
            m.rebind_child(m.current, p_addr)
            m.descend(p_addr)
            switches += 1
            m.ascend(Reason.EXIT, None)

        m.ascend(Reason.EXIT, None)
        expect(m.current.dcb.id == 1, f"hyp after vm{v}")

    m.ascend(Reason.EXIT, None)
    return {"n_vm": n_vm, "n_proc_each": n_proc_each, "switches": switches}


def probe_scale_limits() -> dict:
    """Push until something breaks; record the cliff."""
    findings = {}
    for n in (2, 8, 32, 64, 128):
        try:
            r = probe_many_processes(n)
            findings[f"proc_{n}"] = "ok"
        except Exception as e:
            findings[f"proc_{n}"] = f"{type(e).__name__}: {e}"
            break
    for n in (2, 4, 8, 16):
        try:
            r = probe_many_vms(n, 2)
            findings[f"vm_{n}"] = "ok"
        except Exception as e:
            findings[f"vm_{n}"] = f"{type(e).__name__}: {e}"
            break
    return findings


def probe_sibling_context_isolation() -> None:
    """Two processes must not see each other's regs/pc after switch."""
    m = NPAMachine()
    root = DCB(id=0, entry=0x1000, ptb=0, ipa=0)
    m.boot_root(0x8000, root, Context(pc=0x1000, valid=True))
    kern = DCB(id=1, entry=0x2000, ptb=0, ipa=0)
    m.install_dcb(0x8100, kern)
    m.descend(0x8100)

    a = DCB(id=10, entry=0x3000, ptb=0, ipa=0)
    b = DCB(id=11, entry=0x4000, ptb=0, ipa=0)
    m.install_dcb(0x8200, a)
    m.install_dcb(0x8300, b)

    m.rebind_child(m.current, 0x8200)
    m.descend(0x8200)
    # poke A's context via model
    m.current.ctx.regs[0] = 0xAAAA
    m.current.ctx.pc = 0x3008
    m.ascend(Reason.SERVICE, "a")

    m.rebind_child(m.current, 0x8300)
    m.descend(0x8300)
    expect(m.current.ctx.regs[0] == 0, f"B sees A's reg: {m.current.ctx.regs[0]:#x}")
    m.current.ctx.regs[0] = 0xBBBB
    m.ascend(Reason.SERVICE, "b")

    m.rebind_child(m.current, 0x8200)
    m.descend(0x8200)
    expect(m.current.ctx.regs[0] == 0xAAAA, f"A lost regs: {m.current.ctx.regs[0]:#x}")
    expect(m.current.ctx.pc == 0x3008, f"A lost pc: {m.current.ctx.pc:#x}")
    m.ascend(Reason.EXIT, None)


def probe_two_child_link_leak() -> None:
    """EXIT must terminate domain (fail-fast) and free parent for a new child."""
    m = NPAMachine()
    root = DCB(id=0, entry=0x1000, ptb=0, ipa=0)
    m.boot_root(0x8000, root, Context(pc=0x1000, valid=True))
    a = DCB(id=1, entry=0x2000, ptb=0, ipa=0)
    m.install_dcb(0x8100, a)
    m.descend(0x8100)
    m.ascend(Reason.EXIT, None)
    if m.root.dcb.child != 0:
        raise Probe(f"EXIT did not clear child link: {hex(m.root.dcb.child)}")

    # resume dead domain must fail (invalid/terminated bit)
    m.rebind_child(m.root, 0x8100)
    try:
        m.descend(0x8100)
        raise Probe("descend to terminated domain succeeded")
    except RuntimeError as e:
        if "TERM" not in str(e) and "terminated" not in str(e):
            raise Probe(f"want TERM error, got: {e}")

    # parent reaps, reinstalls as new domain — OK
    m.reap(m.root, 0x8100)
    b = DCB(id=2, entry=0x3000, ptb=0, ipa=0)
    m.install_dcb(0x8100, b)
    m.rebind_child(m.root, 0x8100)
    m.descend(0x8100)
    expect(m.current.dcb.id == 2, f"new domain after reap, got {m.current.dcb.id}")
    expect(m.current.ctx.pc == 0x3000, f"first entry pc, got {m.current.ctx.pc:#x}")
    m.ascend(Reason.EXIT, None)


def main() -> None:
    print("=== scale: many processes ===")
    try:
        r = probe_many_processes(32)
        print("OK ", r)
    except Exception as e:
        print("FAIL", type(e).__name__, e)

    print("=== scale: many VMs × procs ===")
    try:
        r = probe_many_vms(8, 4)
        print("OK ", r)
    except Exception as e:
        print("FAIL", type(e).__name__, e)

    print("=== sibling context isolation ===")
    try:
        probe_sibling_context_isolation()
        print("OK")
    except Exception as e:
        print("FAIL", type(e).__name__, e)

    print("=== EXIT child-link leak ===")
    try:
        probe_two_child_link_leak()
        print("OK")
    except Probe as e:
        print("PROBE", e)
    except Exception as e:
        print("FAIL", type(e).__name__, e)

    print("=== scale limits ===")
    print(probe_scale_limits())


if __name__ == "__main__":
    main()
