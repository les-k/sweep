"""Filesystem walk that locates reclaimable directories, and the deleter."""

from __future__ import annotations

import os
import shutil
import stat
import sys
import time
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable

from .targets import TARGETS, Target

# Directories we never walk into. Descending into these is either pointless or
# actively hostile to the user's machine.
PRUNE_ALWAYS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "$RECYCLE.BIN",
        "System Volume Information",
        "Windows",
        "WinSxS",
    }
)


@dataclass
class Find:
    """A directory sweep believes it can safely reclaim."""

    path: Path
    target: Target
    size: int = 0
    files: int = 0
    unreadable: int = 0
    mtime: float = 0.0

    @property
    def age_days(self) -> float:
        """Days since the directory was last modified."""
        if not self.mtime:
            return 0.0
        return max(0.0, (time.time() - self.mtime) / 86_400)

    @property
    def project(self) -> Path:
        """The project directory that owns this artifact."""
        return self.path.parent


@dataclass
class ScanResult:
    finds: list[Find] = field(default_factory=list)
    roots: list[Path] = field(default_factory=list)
    duration: float = 0.0
    directories_visited: int = 0

    @property
    def total_size(self) -> int:
        return sum(find.size for find in self.finds)

    @property
    def total_files(self) -> int:
        return sum(find.files for find in self.finds)


def _is_excluded(path: Path, patterns: Sequence[str]) -> bool:
    if not patterns:
        return False
    text = str(path)
    name = path.name
    return any(fnmatch(text, pat) or fnmatch(name, pat) for pat in patterns)


def _match(name: str, siblings: frozenset[str], targets: Sequence[Target]) -> Target | None:
    for target in targets:
        if target.matches(name, siblings):
            return target
    return None


def walk(
    root: Path,
    targets: Sequence[Target] = TARGETS,
    exclude: Sequence[str] = (),
    max_depth: int | None = None,
    on_visit: Callable[[Path], None] | None = None,
) -> Iterator[Find]:
    """Yield reclaimable directories under ``root``.

    The walk is iterative (no recursion limit to trip over), never follows
    symlinks or Windows junctions, and does not descend into a directory once
    it has been matched — there is no point costing out the inside of a tree
    that is going to be deleted whole, and it makes scanning a drive full of
    ``node_modules`` roughly as fast as scanning one without.
    """
    stack: list[tuple[Path, int]] = [(root, 0)]

    while stack:
        current, depth = stack.pop()
        if on_visit is not None:
            on_visit(current)
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            # Permission denied, vanished mid-walk, or a device that went away.
            continue

        siblings = frozenset(entry.name for entry in entries)
        descend: list[Path] = []

        for entry in entries:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue

            if entry.name in PRUNE_ALWAYS:
                continue

            path = Path(entry.path)
            if _is_excluded(path, exclude):
                continue

            target = _match(entry.name, siblings, targets)
            if target is not None:
                try:
                    mtime = entry.stat(follow_symlinks=False).st_mtime
                except OSError:
                    mtime = 0.0
                yield Find(path=path, target=target, mtime=mtime)
                continue

            descend.append(path)

        if max_depth is None or depth < max_depth:
            stack.extend((path, depth + 1) for path in descend)


def measure(find: Find) -> Find:
    """Fill in ``size``/``files``/``unreadable`` for a find, in place."""
    total = 0
    files = 0
    unreadable = 0
    stack = [find.path]

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        unreadable += 1
        except OSError:
            unreadable += 1

    find.size = total
    find.files = files
    find.unreadable = unreadable
    return find


def scan(
    roots: Iterable[Path],
    targets: Sequence[Target] = TARGETS,
    exclude: Sequence[str] = (),
    max_depth: int | None = None,
    min_size: int = 0,
    older_than: float | None = None,
    workers: int = 8,
    on_visit: Callable[[Path], None] | None = None,
) -> ScanResult:
    """Scan ``roots`` and return every find that passes the filters.

    Sizing is done on a thread pool: it is pure I/O wait, and on a cold cache
    the pool is worth several times the single-threaded walk.
    """
    started = time.monotonic()
    visited = 0

    def count(path: Path) -> None:
        nonlocal visited
        visited += 1
        if on_visit is not None:
            on_visit(path)

    resolved_roots = []
    found: list[Find] = []
    for root in roots:
        root = Path(root).expanduser().resolve()
        resolved_roots.append(root)
        found.extend(
            walk(root, targets=targets, exclude=exclude, max_depth=max_depth, on_visit=count)
        )

    if found:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            found = list(pool.map(measure, found))

    if min_size:
        found = [find for find in found if find.size >= min_size]
    if older_than is not None:
        found = [find for find in found if find.age_days >= older_than]

    found.sort(key=lambda find: find.size, reverse=True)

    return ScanResult(
        finds=found,
        roots=resolved_roots,
        duration=time.monotonic() - started,
        directories_visited=visited,
    )


def _force_writable(func, path, _exc):  # pragma: no cover - platform specific
    """``rmtree`` error handler for the read-only files pip leaves on Windows."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        raise


def delete(find: Find) -> None:
    """Remove a find from disk.

    Raises ``OSError`` on failure; the caller decides whether that is fatal.
    """
    if sys.version_info >= (3, 12):
        shutil.rmtree(find.path, onexc=_force_writable)
    else:
        shutil.rmtree(find.path, onerror=_force_writable)
