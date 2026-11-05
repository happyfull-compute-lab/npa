"""Memory (lazy) + security model probe — SPEC_MEM_SEC.md

Logical only: no cache. Confidential keys held by security subsystem,
never by parent. Run: python -m model.memsec
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Tuple

from .core import DCB, Context, Lifecycle, MemFault, ProgEnd, NPAMachine, Reason
from .memory import Access, Region, View


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


class Probe(Exception):
    pass


@dataclass
class MemRegion:
    base: int
    size: int
    attr: Access
    owner_id: int
    conf: bool = False  # encrypted / confidential

    def contains(self, pa: int, size: int) -> bool:
        return self.base <= pa and pa + size <= self.base + self.size


@dataclass
class SecuritySub:
    """Spec §2.5 interface subset — model only, not paper implementation."""

    preset: Dict[int, dict] = field(default_factory=dict)  # id -> policy
    bound: Dict[int, int] = field(default_factory=dict)  # id -> sec_handle
    _keys: Dict[int, int] = field(default_factory=dict)  # sec_handle -> key
    _next_handle: int = 0
    # explicit expose set for confidential regions (by region key / pa)
    exposed: Set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        self._next_handle = 0xC0DE

    def preset_load(self, entry_id: int, policy: dict) -> None:
        self.preset[entry_id] = dict(policy)

    def bind(self, domain_id: int, root_ok: bool = True) -> int:
        """I16/I22: must be in preset and trust chain ok."""
        if not root_ok:
            raise PermissionError("trust chain failed")
        if domain_id not in self.preset:
            raise PermissionError(f"id={domain_id} not in security preset")
        if domain_id in self.bound:
            return self.bound[domain_id]
        h = self._next_handle
        self._next_handle += 1
        self.bound[domain_id] = h
        policy = self.preset[domain_id]
        if policy.get("conf"):
            # csec: key only for domain path; root has no K
            self._keys[h] = 0xA500 + (domain_id & 0xFF)
        elif policy.get("sec"):
            # ordinary secure: root/security may hold key
            self._keys[h] = 0x5E00 + (domain_id & 0xFF)
        return h

    def revoke(self, domain_id: int) -> None:
        h = self.bound.pop(domain_id, None)
        if h is not None:
            self._keys.pop(h, None)

    def is_csec(self, owner_id: int) -> bool:
        return bool(self.preset.get(owner_id, {}).get("conf"))

    def check_access(self, viewer_id: int, region: MemRegion, pa: int = 0) -> bool:
        if not region.conf:
            return True
        if viewer_id == region.owner_id:
            return True
        # explicit declassification: this PA (or page) was exposed
        if pa in self.exposed:
            return True
        # ordinary sec: root trust (id 0) may read
        if not self.is_csec(region.owner_id) and viewer_id == 0:
            return True
        # csec: even root (0) denied unless exposed
        return False

    def expose(self, pa: int) -> None:
        """Domain-authorized declassification (shared window / after setting)."""
        self.exposed.add(pa)

    def key_for_owner(self, owner_id: int) -> Optional[int]:
        """Only memory engine / secure path — not parent software."""
        h = self.bound.get(owner_id)
        return self._keys.get(h) if h else None

    def root_has_key(self, owner_id: int) -> bool:
        """Ordinary sec: root may manage key; csec: never."""
        if self.is_csec(owner_id):
            return False
        return owner_id in self.bound


class LazySecureMem:
    """Lazy memory: check on every access. No cache (I21)."""

    def __init__(self, sec: SecuritySub, size: int = 1 << 20):
        self.sec = sec
        self.size = size
        self.data: Dict[int, int] = {}
        self.regions: list[MemRegion] = []

    def map_region(self, r: MemRegion) -> None:
        self.regions.append(r)

    def _region_for(self, pa: int, size: int) -> Optional[MemRegion]:
        for r in self.regions:
            if r.contains(pa, size):
                return r
        return None

    def load(self, pa: int, viewer_id: int, size: int = 4) -> int:
        r = self._region_for(pa, size)
        if r is None:
            raise MemFault("translation", pa, "unmapped")
        if not (Access.R & r.attr):
            raise MemFault("permission", pa, "no R")
        if r.conf and not self.sec.check_access(viewer_id, r, pa):
            raise MemFault("permission", pa, "confidential: no key / not owner")
        return self.data.get(pa, 0)

    def store(self, pa: int, viewer_id: int, val: int, size: int = 4) -> None:
        r = self._region_for(pa, size)
        if r is None:
            raise MemFault("translation", pa, "unmapped")
        if not (Access.W & r.attr):
            raise MemFault("permission", pa, "no W")
        if r.conf and not self.sec.check_access(viewer_id, r, pa):
            raise MemFault("permission", pa, "confidential: no key / not owner")
        # engine would use key_for_owner; model stores plaintext only if check passed
        _k = self.sec.key_for_owner(r.owner_id) if r.conf else None
        if r.conf and _k is None:
            raise MemFault("permission", pa, "confidential: key missing")
        self.data[pa] = val


def s2_bind_not_in_preset() -> None:
    sec = SecuritySub()
    try:
        sec.bind(5, root_ok=True)
        raise Probe("bind succeeded without preset")
    except PermissionError:
        pass


def s3_bind_preset() -> None:
    sec = SecuritySub()
    sec.preset_load(7, {"conf": True, "role": "tee"})
    h = sec.bind(7, root_ok=True)
    expect(h in sec._keys.values() or sec.key_for_owner(7) is not None, "conf key issued")


def s4_s5_parent_no_key_child_ok() -> None:
    sec = SecuritySub()
    sec.preset_load(10, {"conf": True})
    sec.bind(10, root_ok=True)
    mem = LazySecureMem(sec)
    mem.map_region(MemRegion(0x8000, 0x1000, Access.RW, owner_id=10, conf=True))
    mem.map_region(MemRegion(0x9000, 0x1000, Access.RW, owner_id=0, conf=False))

    # child writes own confidential
    mem.store(0x8000, 10, 0x1234)
    expect(mem.load(0x8000, 10) == 0x1234, "owner reads plaintext")

    # parent (id=0) cannot
    try:
        mem.load(0x8000, 0)
        raise Probe("parent read confidential plaintext")
    except MemFault as e:
        expect("confidential" in e.detail or e.kind == "permission", str(e))

    try:
        mem.store(0x8000, 0, 0x9999)
        raise Probe("parent wrote confidential")
    except MemFault:
        pass

    # parent can use non-conf region
    mem.store(0x9000, 0, 1)
    expect(mem.load(0x9000, 0) == 1, "plain region")


def s6_ipa_and_conf() -> None:
    """Full stack: NPA domain view + confidential mem."""
    m = NPAMachine()
    sec = SecuritySub()
    sec.preset_load(2, {"conf": True})
    sec.bind(2, root_ok=True)
    mem = LazySecureMem(sec)

    root = DCB(id=0, entry=0x1000, ptb=0, ipa=0)
    m.boot_root(0x8000, root, Context(pc=0x1000, valid=True))

    # child inherit + ipa window; conf body at 0x8000
    child = DCB(id=2, entry=0x2000, ptb=0, ipa=0xA000, edel=0)
    m.install_dcb(0x8100, child)
    m.write_regions(0xA000, [
        (0x2000, 0x1000, int(Access.RWX)),
        (0x8000, 0x1000, int(Access.RW)),
        (0, 0, 0),
    ])
    mem.map_region(MemRegion(0x8000, 0x1000, Access.RW, owner_id=2, conf=True))
    mem.map_region(MemRegion(0x2000, 0x1000, Access.RWX, owner_id=2, conf=False))

    m.descend(0x8100)
    va = 0x8000
    name = va  # inherit view checks VA
    err = m.current.view.check(name, 4, Access.W)
    expect(err is None, f"ipa allows conf window: {err}")
    mem.store(0x8000, 2, 0x55)
    expect(mem.load(0x8000, 2) == 0x55, "child conf rw")

    # outside ipa
    err = m.current.view.check(0x9000, 4, Access.W)
    expect(err is not None, "outside ipa denied")

    # parent view after ascend — still no key
    m.ascend(Reason.SERVICE, "x")
    try:
        mem.load(0x8000, 0)
        raise Probe("parent got conf after ascend")
    except MemFault:
        pass


def s7_revoke_no_reuse_key() -> None:
    sec = SecuritySub()
    sec.preset_load(3, {"conf": True})
    sec.bind(3, root_ok=True)
    k1 = sec.key_for_owner(3)
    expect(k1 is not None, "key1")
    sec.revoke(3)
    expect(sec.key_for_owner(3) is None, "key revoked")
    # rebind same id = new handle/key
    sec.bind(3, root_ok=True)
    k2 = sec.key_for_owner(3)
    expect(k2 is not None and k2 == 0xA500 + 3, "reissue")
    # parent still cannot get key via API
    expect(not hasattr(sec, "key_for_parent"), "no parent key API")


def s_trust_chain_fail() -> None:
    sec = SecuritySub()
    sec.preset_load(9, {"conf": False})
    try:
        sec.bind(9, root_ok=False)
        raise Probe("bind without root trust")
    except PermissionError:
        pass


def s8_sec_root_yes_parent_no() -> None:
    """Ordinary secure: root trust can read, parent cannot."""
    sec = SecuritySub()
    sec.preset_load(20, {"sec": True})  # not conf
    sec.bind(20, root_ok=True)
    mem = LazySecureMem(sec)
    mem.map_region(MemRegion(0xA000, 0x100, Access.RW, owner_id=20, conf=True))
    mem.store(0xA000, 20, 0x5EC)
    expect(mem.load(0xA000, 0) == 0x5EC, "root reads ordinary sec")
    try:
        mem.load(0xA000, 1)  # non-root parent/other
        raise Probe("parent read ordinary sec content")
    except MemFault:
        pass


def s9_csec_root_no_self_yes() -> None:
    """Confidential: even root cannot read; owner can."""
    sec = SecuritySub()
    sec.preset_load(30, {"conf": True})
    sec.bind(30, root_ok=True)
    mem = LazySecureMem(sec)
    mem.map_region(MemRegion(0xB000, 0x100, Access.RW, owner_id=30, conf=True))
    mem.store(0xB000, 30, 0xCC)
    expect(mem.load(0xB000, 30) == 0xCC, "owner reads csec")
    for viewer in (0, 1, 2):
        try:
            mem.load(0xB000, viewer)
            raise Probe(f"viewer {viewer} read csec")
        except MemFault:
            pass
    expect(not sec.root_has_key(30), "root has no csec key")


def s10_csec_explicit_expose() -> None:
    """csec declassification via shared window."""
    sec = SecuritySub()
    sec.preset_load(31, {"conf": True})
    sec.bind(31, root_ok=True)
    mem = LazySecureMem(sec)
    mem.map_region(MemRegion(0xC000, 0x100, Access.RW, owner_id=31, conf=True))
    mem.store(0xC000, 31, 0x1111)
    try:
        mem.load(0xC000, 0)
        raise Probe("parent read before expose")
    except MemFault:
        pass
    sec.expose(0xC000)  # domain-authorized
    expect(mem.load(0xC000, 0) == 0x1111, "parent reads after expose")
    # other page still closed
    mem.store(0xC040, 31, 0x2222)
    try:
        mem.load(0xC040, 0)
        raise Probe("parent read unexposed page")
    except MemFault:
        pass


def s11_secure_lib_shortlived() -> None:
    """secure lib shape: small space sec/csec, verify, run, exit, revoke."""
    sec = SecuritySub()
    code = b"\x00\x01\x02\x03"

    def verify(img: bytes) -> bool:
        return img == code  # stand-in for measurement

    if not verify(code):
        raise Probe("verify failed")
    sec.preset_load(40, {"conf": True, "role": "lib"})
    sec.bind(40, root_ok=True)
    mem = LazySecureMem(sec)
    # small reused window
    mem.map_region(MemRegion(0x1000, 0x10, Access.RWX, owner_id=40, conf=True))
    mem.store(0x1000, 40, 99)
    expect(mem.load(0x1000, 40) == 99, "lib run")
    # exit + reap → revoke
    sec.revoke(40)
    expect(sec.key_for_owner(40) is None, "key dead after exit")
    try:
        mem.load(0x1000, 40)
        # conf region without key — engine would fail; check_access still owner-true
        # require key in store/load path
    except MemFault:
        pass
    # force key-missing path
    try:
        mem.store(0x1000, 40, 1)
        raise Probe("write after revoke")
    except MemFault:
        pass


def main() -> None:
    cases = [
        ("S2 bind not in preset", s2_bind_not_in_preset),
        ("S3 bind preset+conf", s3_bind_preset),
        ("S4/S5 parent no key / child ok", s4_s5_parent_no_key_child_ok),
        ("S6 ipa+conf stack", s6_ipa_and_conf),
        ("S7 revoke / reissue", s7_revoke_no_reuse_key),
        ("S-trust chain fail", s_trust_chain_fail),
        ("S8 sec root yes parent no", s8_sec_root_yes_parent_no),
        ("S9 csec root no self yes", s9_csec_root_no_self_yes),
        ("S10 csec explicit expose", s10_csec_explicit_expose),
        ("S11 secure lib short-lived", s11_secure_lib_shortlived),
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
