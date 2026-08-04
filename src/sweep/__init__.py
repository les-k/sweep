"""sweep - find and reclaim regenerable build artifacts.

The public surface is deliberately small:

    >>> from sweep import scan
    >>> result = scan(["."])
    >>> result.total_size
    0
"""

from __future__ import annotations

__version__ = "0.1.0"

from .scanner import Find, ScanResult, delete, scan, walk  # noqa: E402
from .targets import TARGETS, Target  # noqa: E402

__all__ = [
    "__version__",
    "Find",
    "ScanResult",
    "Target",
    "TARGETS",
    "delete",
    "scan",
    "walk",
]
