"""Human-readable rendering for scan results."""

from __future__ import annotations

import os
import sys

from .scanner import ScanResult

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


class Palette:
    """ANSI colours, or empty strings when colour is off."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)


def supports_colour(stream=sys.stdout) -> bool:
    """Whether it is safe to emit ANSI escapes on ``stream``."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def human_size(size: float) -> str:
    """Format a byte count the way ``du -h`` would."""
    if size < 1024:
        return f"{int(size)} B"
    value = float(size)
    for unit in _UNITS[1:]:
        value /= 1024
        if value < 1024:
            precision = 1 if value < 10 else 0
            return f"{value:.{precision}f} {unit}"
    return f"{value:.1f} {_UNITS[-1]}"


def human_age(days: float) -> str:
    if days < 1:
        return "today"
    if days < 2:
        return "1 day"
    if days < 60:
        return f"{int(days)} days"
    if days < 730:
        return f"{int(days / 30)} months"
    return f"{days / 365:.1f} years"


def shorten(path, width: int) -> str:
    """Trim a path from the left so it fits ``width``, keeping the tail."""
    text = str(path)
    if len(text) <= width:
        return text
    return "..." + text[-(width - 3) :]


def render_table(result: ScanResult, palette: Palette, limit: int, width: int = 100) -> str:
    """The per-directory listing, largest first."""
    if not result.finds:
        return palette.green("Nothing to reclaim - everything here is already clean.")

    shown = result.finds[:limit] if limit else result.finds
    size_width = max(len(human_size(find.size)) for find in shown)
    kind_width = max(len(find.target.key) for find in shown)
    path_width = max(24, width - size_width - kind_width - 14)

    lines = []
    for find in shown:
        size = human_size(find.size).rjust(size_width)
        kind = find.target.key.ljust(kind_width)
        age = human_age(find.age_days).rjust(9)
        lines.append(
            f"  {palette.bold(size)}  {palette.cyan(kind)}  "
            f"{palette.dim(age)}  {shorten(find.path, path_width)}"
        )

    hidden = len(result.finds) - len(shown)
    if hidden > 0:
        hidden_size = sum(find.size for find in result.finds[limit:])
        lines.append(
            palette.dim(
                f"  ... and {hidden} more, totalling {human_size(hidden_size)} "
                f"(use --limit 0 to list them all)"
            )
        )
    return "\n".join(lines)


def render_summary(result: ScanResult, palette: Palette) -> str:
    """Totals grouped by target kind, plus the headline number."""
    if not result.finds:
        return ""

    by_key: dict[str, tuple[int, int]] = {}
    for find in result.finds:
        count, size = by_key.get(find.target.key, (0, 0))
        by_key[find.target.key] = (count + 1, size + find.size)

    rows = sorted(by_key.items(), key=lambda item: item[1][1], reverse=True)
    key_width = max(len(key) for key, _ in rows)

    lines = [palette.bold("By kind")]
    for key, (count, size) in rows:
        label = f"{count} dir" if count == 1 else f"{count} dirs"
        lines.append(f"  {key.ljust(key_width)}  {human_size(size).rjust(9)}  {palette.dim(label)}")

    unreadable = sum(find.unreadable for find in result.finds)
    lines.append("")
    lines.append(
        palette.bold(
            f"{len(result.finds)} directories, {result.total_files:,} files, "
            f"{palette.green(human_size(result.total_size))} reclaimable"
        )
    )
    lines.append(
        palette.dim(f"scanned {result.directories_visited:,} directories in {result.duration:.1f}s")
    )
    if unreadable:
        lines.append(
            palette.yellow(f"{unreadable} entries could not be read and are not counted above")
        )
    return "\n".join(lines)


def render_json(result: ScanResult) -> dict:
    """A machine-readable view of the scan, for piping into other tools."""
    return {
        "roots": [str(root) for root in result.roots],
        "duration_seconds": round(result.duration, 3),
        "directories_visited": result.directories_visited,
        "total_size_bytes": result.total_size,
        "total_files": result.total_files,
        "finds": [
            {
                "path": str(find.path),
                "project": str(find.project),
                "kind": find.target.key,
                "ecosystem": find.target.ecosystem,
                "size_bytes": find.size,
                "files": find.files,
                "age_days": round(find.age_days, 2),
                "regenerate_with": find.target.regenerate,
            }
            for find in result.finds
        ],
    }
