# sweep

[![CI](https://github.com/lesliekadenge/sweep/actions/workflows/ci.yml/badge.svg)](https://github.com/lesliekadenge/sweep/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%20%E2%80%93%203.13-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Find and reclaim the disk space your projects are quietly sitting on — `node_modules`,
`.venv`, `target/`, `__pycache__` and friends — without touching anything you actually wrote.

No dependencies. One file to read per concept. Reports by default; deletes only when asked.

---

## The problem

Every project you build leaves behind directories that aren't your code. A single
JavaScript project's `node_modules` routinely runs 200 MB–1 GB. Work through a
year of side projects and tutorials and you're tens of gigabytes down, spread
across folders you've long since forgotten.

All of it is *regenerable*: delete it, run `npm install`, and it comes back. It's
pure waste — but finding it means remembering where every project lives, and
deleting it by hand means being very sure you typed the right path.

## What it looks like

```console
$ sweep ~/code
   1.4 GB  node-modules      12 days  ~/code/portfolio-site/node_modules
   890 MB  rust-target        3 days  ~/code/raytracer/target
   412 MB  node-modules      8 months  ~/code/old-tutorial/node_modules
   198 MB  venv              5 months  ~/code/scrapers/.venv
   103 KB  pycache            today   ~/code/scrapers/tests/__pycache__

By kind
  node-modules      1.8 GB  2 dirs
  rust-target       890 MB  1 dir
  venv              198 MB  1 dir
  pycache           103 KB  1 dir

5 directories, 48,201 files, 2.9 GB reclaimable
scanned 3,847 directories in 1.2s

Nothing was deleted. Re-run with --delete to reclaim the space.
```

Happy with the list? Add `--delete`.

## Install

Requires Python 3.9+.

```bash
pipx install git+https://github.com/lesliekadenge/sweep.git
```

Or with plain pip:

```bash
pip install git+https://github.com/lesliekadenge/sweep.git
```

## Usage

```bash
sweep                                  # report on the current directory
sweep ~/code ~/work                    # scan several roots at once
sweep ~/code --min-size 100MB          # only the space that's worth reclaiming
sweep ~/code --older-than 90           # only projects untouched for 3 months
sweep ~/code --only node-modules       # one kind of artifact
sweep ~/code --delete                  # reclaim it, after a confirmation prompt
sweep ~/code --delete --yes            # reclaim it, no prompt (for scripts)
```

`sweep` never deletes without `--delete`, and `--delete` always prompts unless
you pass `--yes`.

## How it decides what's safe

This is the part that matters. `rm -rf node_modules` is a one-liner; the reason
`sweep` exists is that "delete every directory named `build`" is a genuinely bad
idea, and telling the good ones from the bad ones takes a rule.

The rule: **a directory is only reclaimable if something on disk proves it can be
rebuilt.** That evidence comes in two forms.

**Pure caches** are always fair game. `__pycache__`, `.pytest_cache`,
`.ruff_cache` — these have no other purpose, and the tool that made them will
remake them without being asked. No further proof needed.

**Everything else needs a marker file** sitting next to it. `node_modules` counts
only if `package.json` is its sibling — that file *is* the receipt proving
`npm install` can restore it. `target/` counts only next to `Cargo.toml`.
`build/` counts only next to `pyproject.toml` or `build.gradle`.

The consequence is the useful bit:

```
code/portfolio/                    code/notes/
  package.json      <- receipt       target/           <- no receipt
  node_modules/     RECLAIMED          research.md     LEFT ALONE
```

A `target/` directory you created by hand to hold your own files has no
`Cargo.toml` beside it, so `sweep` doesn't recognise it and doesn't touch it.
Same directory name, opposite outcome, decided by evidence rather than by a
hardcoded list of names.

Markers also disambiguate collisions. Both Cargo and Maven build into `target/`;
the marker tells `sweep` which one it's looking at, so the report says
`rust-target` or `maven-target` and tells you the right command to rebuild it.

Two more guarantees worth stating:

- **Symlinks and Windows junctions are never followed** — not when walking, not
  when adding up sizes. A link inside a cache can't lead `sweep` out into the
  rest of your filesystem.
- **`.git`, `.hg`, and `.svn` are never entered.** Your history is not a build
  artifact.

Run `sweep --list-targets` to see all 24 kinds, what each one needs as proof, and
the exact command that brings it back.

## What it knows about

| Kind | Matches | Proof required | Comes back with |
|---|---|---|---|
| `node-modules` | `node_modules` | `package.json` | `npm install` |
| `venv` | `.venv`, `venv` | `pyproject.toml`, `requirements.txt`, … | `pip install -e .` |
| `rust-target` | `target` | `Cargo.toml` | `cargo build` |
| `maven-target` | `target` | `pom.xml` | `mvn package` |
| `gradle-build` | `build`, `.gradle` | `build.gradle` | `gradle build` |
| `dotnet-build` | `bin`, `obj` | `*.csproj`, `*.sln` | `dotnet build` |
| `python-build` | `build`, `dist`, `*.egg-info` | `pyproject.toml` | `python -m build` |
| `terraform` | `.terraform` | `*.tf` | `terraform init` |
| `pycache` | `__pycache__` | — pure cache | automatic |
| `pytest-cache` | `.pytest_cache` | — pure cache | automatic |

…and 14 more, covering Next.js, Nuxt, Turbo, Parcel, Vite, nyc, tox/nox, mypy,
ruff, coverage, Jupyter checkpoints, Go, CMake, and Gradle's caches. Eleven of
the 24 are pure caches needing no marker; the other thirteen all require proof.

## Options

```
positional arguments:
  paths                 directories to scan (default: the current directory)

actions:
  -d, --delete          delete what is found (default is report-only)
  -y, --yes             skip the confirmation prompt for --delete
  --list-targets        list every target kind and exit

filters:
  --min-size SIZE       ignore directories smaller than this (e.g. 100MB)
  --older-than DAYS     only include directories untouched for at least DAYS days
  --only KIND           restrict to these target kinds (repeatable, comma-separated)
  --skip KIND           exclude these target kinds (repeatable, comma-separated)
  --ecosystem NAME      restrict to an ecosystem (javascript, python, rust, jvm, …)
  --exclude GLOB        skip paths matching this glob (repeatable)
  --depth N             stop descending after N levels

output:
  --limit N             show at most N directories, 0 for all (default: 25)
  --json                emit JSON instead of a table
  --no-color            disable ANSI colour
  -q, --quiet           suppress progress output
```

## Scripting

`--json` gives you the whole scan, machine-readable:

```bash
sweep ~/code --json | jq '.total_size_bytes'
sweep ~/code --json | jq -r '.finds[] | select(.age_days > 180) | .path'
```

```json
{
  "roots": ["/home/leslie/code"],
  "duration_seconds": 1.23,
  "directories_visited": 3847,
  "total_size_bytes": 3113851289,
  "total_files": 48201,
  "finds": [
    {
      "path": "/home/leslie/code/portfolio-site/node_modules",
      "project": "/home/leslie/code/portfolio-site",
      "kind": "node-modules",
      "ecosystem": "javascript",
      "size_bytes": 1503238553,
      "files": 31204,
      "age_days": 12.4,
      "regenerate_with": "npm install"
    }
  ]
}
```

There's also a small Python API, if you'd rather not shell out:

```python
from sweep import scan

result = scan(["~/code"], min_size=100 * 1024**2)
print(f"{result.total_size / 1024**3:.1f} GB across {len(result.finds)} directories")

for find in result.finds:
    print(find.path, find.target.regenerate)
```

## How it works

Three modules, each with one job:

| File | Responsibility |
|---|---|
| [`targets.py`](src/sweep/targets.py) | The catalogue — what counts as reclaimable, and what proof each kind needs |
| [`scanner.py`](src/sweep/scanner.py) | Walking the filesystem, sizing what it finds, deleting on request |
| [`formatting.py`](src/sweep/formatting.py) | Turning results into a table, a summary, or JSON |

The walk is iterative rather than recursive (no recursion limit to trip over on
deep trees) and **stops descending the moment it matches**. There's no point
costing out the inside of a tree that's going to be deleted whole — which is why
scanning a drive full of `node_modules` costs about the same as scanning one
without. Sizing then runs on a thread pool, since it's pure I/O wait.

Errors are swallowed at the leaves by design: a permission-denied directory, a
file that vanishes mid-scan, or a disconnected network drive shouldn't abort a
scan of your whole home directory. Anything unreadable is counted and reported at
the bottom of the summary rather than silently dropped.

## Development

```bash
git clone https://github.com/lesliekadenge/sweep.git
cd sweep
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

75 tests, 88% coverage. CI runs the suite on Python 3.9–3.13 on Linux, plus
Windows and macOS, and checks lint and formatting with `ruff`.

The tests build real directory trees on disk rather than mocking the filesystem —
including a deliberate decoy pair (a `node_modules` with no `package.json`, a
hand-written `target/` with no `Cargo.toml`) that asserts the marker rule holds.
Windows read-only files and symlink escapes are covered too, since those are
where a tool like this does real damage if it's wrong.

## License

MIT — see [LICENSE](LICENSE).
