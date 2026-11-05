"""Minimal NPA model — probe against SPEC_NPA_CORE.md (v0.1).

Not a full ISA simulator. Goal: exercise domain tree, descend/ascend,
DCB Spec, Context, and address views (inherit / stacked / constrained).
"""

from .core import (
    DCB,
    Context,
    Domain,
    Lifecycle,
    Reason,
    NPAMachine,
    MemFault,
    ProgEnd,
)
from .memory import Access, Region, View

__all__ = [
    "DCB",
    "Context",
    "Domain",
    "Lifecycle",
    "Reason",
    "NPAMachine",
    "MemFault",
    "ProgEnd",
    "Access",
    "Region",
    "View",
]
