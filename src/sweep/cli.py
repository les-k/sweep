"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .formatting import (
    Palette,
    human_size,
    render_json,
    render_summary,
    render_table,
    supports_colour,
)
from .scanner import Find, ScanResult, delete, scan
from .targets import TARGETS, TARGETS_BY_KEY, Target, ecosystems

_SIZE_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([kmgtp]?)b?\s*$", re.IGNORECASE)
_SIZE_MULTIPLIERS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4, "p": 1024**5}


def parse_size(text: str) -> int:
    """Turn ``"500MB"`` / ``"1.5G"`` / ``"2048"`` into a byte count."""
    match = _SIZE_RE.match(text)
    if not match:
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a size (try 500MB, 1.5G, or a plain byte count)"
        )
    number, suffix = match.groups()
    return int(float(number) * _SIZE_MULTIPLIERS[suffix.lower()])


def _split_keys(values: Sequence[str]) -> list[str]:
    """Flatten repeated and comma-joined ``--only``/``--skip`` values."""
    keys: list[str] = []
    for value in values:
        keys.extend(part.strip() for part in value.split(",") if part.strip())
    return keys


def select_targets(
    only: Sequence[str], skip: Sequence[str], eco: Sequence[str]
) -> tuple[Target, ...]:
    """Apply ``--only`` / ``--skip`` / ``--ecosystem`` to the target catalogue."""
    unknown = [key for key in (*only, *skip) if key not in TARGETS_BY_KEY]
    if unknown:
        raise SystemExit(
            f"sweep: unknown target {unknown[0]!r}. Run 'sweep --list-targets' to see them all."
        )
    unknown_eco = [name for name in eco if name not in ecosystems()]
    if unknown_eco:
        raise SystemExit(
            f"sweep: unknown ecosystem {unknown_eco[0]!r}. Known: {', '.join(ecosystems())}."
        )

    chosen = TARGETS
    if only:
        chosen = tuple(target for target in chosen if target.key in set(only))
    if eco:
        chosen = tuple(target for target in chosen if target.ecosystem in set(eco))
    if skip:
        chosen = tuple(target for target in chosen if target.key not in set(skip))
    if not chosen:
        raise SystemExit("sweep: those filters leave no targets to look for.")
    return chosen


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sweep",
        description=(
            "Find and reclaim regenerable build artifacts - node_modules, .venv, "
            "target/, __pycache__ and friends. Reports by default; only deletes "
            "when you ask it to."
        ),
        epilog=(
            "examples:\n"
            "  sweep                        report on the current directory\n"
            "  sweep ~/code --min-size 100MB\n"
            "  sweep ~/code --older-than 90 --delete\n"
            "  sweep --only node-modules --json | jq '.total_size_bytes'\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[Path.cwd()],
        help="directories to scan (default: the current directory)",
    )

    action = parser.add_argument_group("actions")
    action.add_argument(
        "-d", "--delete", action="store_true", help="delete what is found (default is report-only)"
    )
    action.add_argument(
        "-y", "--yes", action="store_true", help="skip the confirmation prompt for --delete"
    )
    action.add_argument(
        "--list-targets", action="store_true", help="list every target kind and exit"
    )

    filters = parser.add_argument_group("filters")
    filters.add_argument(
        "--min-size",
        type=parse_size,
        default=0,
        metavar="SIZE",
        help="ignore directories smaller than this (e.g. 100MB)",
    )
    filters.add_argument(
        "--older-than",
        type=float,
        default=None,
        metavar="DAYS",
        help="only include directories untouched for at least DAYS days",
    )
    filters.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="KIND",
        help="restrict to these target kinds (repeatable, comma-separated)",
    )
    filters.add_argument(
        "--skip",
        action="append",
        default=[],
        metavar="KIND",
        help="exclude these target kinds (repeatable, comma-separated)",
    )
    filters.add_argument(
        "--ecosystem",
        action="append",
        default=[],
        metavar="NAME",
        help=f"restrict to an ecosystem ({', '.join(ecosystems())})",
    )
    filters.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="skip paths matching this glob (repeatable)",
    )
    filters.add_argument(
        "--depth",
        type=int,
        default=None,
        metavar="N",
        help="stop descending after N levels",
    )

    output = parser.add_argument_group("output")
    output.add_argument(
        "--limit",
        type=int,
        default=25,
        metavar="N",
        help="show at most N directories, 0 for all (default: 25)",
    )
    output.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    output.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    output.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")
    output.add_argument("--version", action="version", version=f"sweep {__version__}")
    return parser


def _list_targets(palette: Palette) -> int:
    key_width = max(len(target.key) for target in TARGETS)
    eco_width = max(len(target.ecosystem) for target in TARGETS)
    print(palette.bold("Target kinds sweep knows about\n"))
    for target in TARGETS:
        guard = (
            palette.dim(f"needs {'/'.join(target.markers)} alongside")
            if target.needs_marker
            else palette.dim("always safe (pure cache)")
        )
        print(
            f"  {palette.cyan(target.key.ljust(key_width))}  "
            f"{target.ecosystem.ljust(eco_width)}  "
            f"{', '.join(target.patterns)}"
        )
        print(f"  {' ' * key_width}  {' ' * eco_width}  {guard}")
        print(
            f"  {' ' * key_width}  {' ' * eco_width}  {palette.dim('back via: ' + target.regenerate)}"
        )
        print()
    return 0


class _Progress:
    """Throttled one-line progress written to stderr."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.count = 0
        self._last = 0.0

    def __call__(self, path: Path) -> None:
        if not self.enabled:
            return
        self.count += 1
        now = time.monotonic()
        if now - self._last < 0.1:
            return
        self._last = now
        line = f"  scanning... {self.count:,} directories"
        sys.stderr.write(f"\r{line[:78].ljust(78)}")
        sys.stderr.flush()

    def clear(self) -> None:
        if self.enabled:
            sys.stderr.write("\r" + " " * 78 + "\r")
            sys.stderr.flush()


def _confirm(result: ScanResult, palette: Palette) -> bool:
    prompt = (
        f"\nDelete {len(result.finds)} directories "
        f"({palette.bold(human_size(result.total_size))})? [y/N] "
    )
    try:
        answer = input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer.strip().lower() in {"y", "yes"}


def _do_delete(result: ScanResult, palette: Palette, quiet: bool) -> int:
    reclaimed = 0
    failures: list[tuple[Find, OSError]] = []

    for find in result.finds:
        try:
            delete(find)
        except OSError as exc:
            failures.append((find, exc))
            continue
        reclaimed += find.size
        if not quiet:
            print(f"  {palette.green('removed')} {find.path}")

    print()
    print(palette.bold(f"Reclaimed {palette.green(human_size(reclaimed))}."))

    if failures:
        print()
        print(palette.yellow(f"{len(failures)} directories could not be removed:"))
        for find, exc in failures[:10]:
            print(f"  {find.path}: {exc.strerror or exc}")
        if len(failures) > 10:
            print(f"  ... and {len(failures) - 10} more")
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    use_colour = not args.no_color and supports_colour()
    palette = Palette(use_colour and not args.json)

    if args.list_targets:
        return _list_targets(palette)

    targets = select_targets(_split_keys(args.only), _split_keys(args.skip), args.ecosystem)

    for path in args.paths:
        if not Path(path).expanduser().is_dir():
            print(f"sweep: {path} is not a directory", file=sys.stderr)
            return 2

    progress = _Progress(enabled=not args.quiet and not args.json and sys.stderr.isatty())
    try:
        result = scan(
            args.paths,
            targets=targets,
            exclude=args.exclude,
            max_depth=args.depth,
            min_size=args.min_size,
            older_than=args.older_than,
            on_visit=progress,
        )
    except KeyboardInterrupt:
        progress.clear()
        print("sweep: interrupted", file=sys.stderr)
        return 130
    finally:
        progress.clear()

    if args.json:
        json.dump(render_json(result), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print(render_table(result, palette, limit=max(0, args.limit)))
    if not result.finds:
        return 0
    print()
    print(render_summary(result, palette))

    if not args.delete:
        print()
        print(palette.dim("Nothing was deleted. Re-run with --delete to reclaim the space."))
        return 0

    if not args.yes and not _confirm(result, palette):
        print("Cancelled.")
        return 0

    print()
    return _do_delete(result, palette, quiet=args.quiet)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
