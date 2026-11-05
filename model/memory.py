"""Address views: inherit, stacked, and permission-constrained inherit.

SPEC_NPA_CORE §5:
  ptb == 0  and  ipa == 0  -> INHERIT (share parent's translation)
  ptb == 0  and  ipa != 0  -> INHERIT + constraint table  [PROBE: see notes]
  ptb != 0                 -> stacked (child VA -> parent-view addr)

Constraint table entries: (base, size, attr) with attr in {R, RW, RX, RWX}.
Zero-size entry terminates. This is the same table shape as ipa_regions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntFlag, auto
from typing import Dict, List, Optional, Tuple


class Access(IntFlag):
    R = auto()
    W = auto()
    X = auto()
    RW = R | W
    RX = R | X
    RWX = R | W | X


@dataclass(frozen=True)
class Region:
    base: int
    size: int
    attr: Access

    def contains(self, addr: int, size: int) -> bool:
        return self.base <= addr and addr + size <= self.base + self.size


@dataclass
class View:
    """Resolved address view for the current domain."""

    inherit: bool
    # VA -> parent-view address (one level); empty if inherit
    pt: Dict[int, int] = field(default_factory=dict)
    # Constraint table:
    #   inherit=True  -> checked on VA (same names as parent; permission overlay)
    #   inherit=False -> checked on parent-view address after this level's PT (IPA bounds)
    allow: List[Region] = field(default_factory=list)
    # For stacked domains: parent's view (for chaining VA->...->PA)
    parent_view: Optional["View"] = None

    def translate_one(self, va: int) -> int:
        if self.inherit:
            return va
        if va not in self.pt:
            raise KeyError(va)
        return self.pt[va]

    def translate(self, va: int) -> int:
        """Chain to final PA."""
        if self.inherit:
            # same address space as parent: reuse parent's full translation
            if self.parent_view is not None:
                return self.parent_view.translate(va)
            return va
        addr = self.translate_one(va)
        if self.parent_view is not None:
            return self.parent_view.translate(addr)
        return addr

    def check(self, name: int, size: int, acc: Access) -> Optional[str]:
        """Check allow-list against `name` (VA if inherit, else IPA after one level)."""
        if not self.allow:
            return None
        for r in self.allow:
            if r.contains(name, size) and (acc & r.attr) == acc:
                return None
        return f"access {acc} at 0x{name:x}+{size} not in allow-list"


def parse_regions(words: List[Tuple[int, int, int]]) -> List[Region]:
    out: List[Region] = []
    for base, size, attr in words:
        if base == 0 and size == 0 and attr == 0:
            break
        out.append(Region(base, size, Access(attr)))
    return out
