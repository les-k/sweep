"""Catalogue of the build artifacts and caches that sweep knows how to reclaim.

Every entry here has to satisfy one rule: the directory must be *regenerable*.
Either it is a pure cache that its tool rebuilds on demand, or it can only be
matched when a sibling marker file proves the project that produced it is still
present (``package.json`` next to ``node_modules``, ``Cargo.toml`` next to
``target``).  That marker requirement is what keeps sweep from eating a
hand-written ``build/`` directory that merely shares a name with a real one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatch


@dataclass(frozen=True)
class Target:
    """One kind of reclaimable directory."""

    key: str
    """Stable identifier, used by ``--only`` and ``--skip``."""

    ecosystem: str
    """Human grouping for the summary table."""

    patterns: Sequence[str]
    """Directory names to match, as fnmatch globs."""

    regenerate: str
    """The command (or non-command) that brings the directory back."""

    markers: Sequence[str] = field(default_factory=tuple)
    """Sibling files that must exist for a match to count.

    Empty means the directory is a self-evident cache and is always matchable.
    Any one marker is enough.
    """

    def matches(self, name: str, siblings: frozenset[str]) -> bool:
        """Whether ``name`` is an instance of this target.

        ``siblings`` is the set of entry names in the *parent* directory, which
        is where marker files live.
        """
        if not any(fnmatch(name, pattern) for pattern in self.patterns):
            return False
        if not self.markers:
            return True
        return any(any(fnmatch(sibling, marker) for sibling in siblings) for marker in self.markers)

    @property
    def needs_marker(self) -> bool:
        return bool(self.markers)


TARGETS: tuple[Target, ...] = (
    # -- JavaScript / TypeScript ------------------------------------------
    Target(
        key="node-modules",
        ecosystem="javascript",
        patterns=("node_modules",),
        markers=("package.json",),
        regenerate="npm install",
    ),
    Target(
        key="next",
        ecosystem="javascript",
        patterns=(".next",),
        markers=("package.json",),
        regenerate="npm run build",
    ),
    Target(
        key="nuxt",
        ecosystem="javascript",
        patterns=(".nuxt", ".output"),
        markers=("nuxt.config.js", "nuxt.config.ts"),
        regenerate="nuxt build",
    ),
    Target(
        key="turbo",
        ecosystem="javascript",
        patterns=(".turbo",),
        markers=("package.json",),
        regenerate="rebuilt by turbo on next run",
    ),
    Target(
        key="parcel-cache",
        ecosystem="javascript",
        patterns=(".parcel-cache",),
        regenerate="rebuilt by parcel on next run",
    ),
    Target(
        key="vite-cache",
        ecosystem="javascript",
        patterns=(".vite",),
        regenerate="rebuilt by vite on next run",
    ),
    Target(
        key="nyc-output",
        ecosystem="javascript",
        patterns=(".nyc_output",),
        regenerate="re-run the test suite with coverage",
    ),
    # -- Python ------------------------------------------------------------
    Target(
        key="pycache",
        ecosystem="python",
        patterns=("__pycache__",),
        regenerate="rebuilt by CPython on next import",
    ),
    Target(
        key="venv",
        ecosystem="python",
        patterns=(".venv", "venv"),
        markers=("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg"),
        regenerate="python -m venv .venv && pip install -e .",
    ),
    Target(
        key="python-build",
        ecosystem="python",
        patterns=("build", "dist", "*.egg-info"),
        markers=("pyproject.toml", "setup.py"),
        regenerate="python -m build",
    ),
    Target(
        key="tox",
        ecosystem="python",
        patterns=(".tox", ".nox"),
        markers=("tox.ini", "noxfile.py", "pyproject.toml"),
        regenerate="tox",
    ),
    Target(
        key="pytest-cache",
        ecosystem="python",
        patterns=(".pytest_cache",),
        regenerate="rebuilt by pytest on next run",
    ),
    Target(
        key="mypy-cache",
        ecosystem="python",
        patterns=(".mypy_cache", ".pytype", ".pyre"),
        regenerate="rebuilt by the type checker on next run",
    ),
    Target(
        key="ruff-cache",
        ecosystem="python",
        patterns=(".ruff_cache",),
        regenerate="rebuilt by ruff on next run",
    ),
    Target(
        key="coverage",
        ecosystem="python",
        patterns=("htmlcov",),
        regenerate="coverage html",
    ),
    Target(
        key="notebook-checkpoints",
        ecosystem="python",
        patterns=(".ipynb_checkpoints",),
        regenerate="rebuilt by Jupyter on next save",
    ),
    # -- Compiled languages -------------------------------------------------
    Target(
        key="rust-target",
        ecosystem="rust",
        patterns=("target",),
        markers=("Cargo.toml",),
        regenerate="cargo build",
    ),
    Target(
        key="maven-target",
        ecosystem="jvm",
        patterns=("target",),
        markers=("pom.xml",),
        regenerate="mvn package",
    ),
    Target(
        key="gradle-build",
        ecosystem="jvm",
        patterns=("build", ".gradle"),
        markers=("build.gradle", "build.gradle.kts", "settings.gradle"),
        regenerate="gradle build",
    ),
    Target(
        key="dotnet-build",
        ecosystem="dotnet",
        patterns=("bin", "obj"),
        markers=("*.csproj", "*.fsproj", "*.vbproj", "*.sln"),
        regenerate="dotnet build",
    ),
    Target(
        key="go-build-cache",
        ecosystem="go",
        patterns=(".gocache",),
        regenerate="rebuilt by go on next build",
    ),
    Target(
        key="cmake-build",
        ecosystem="native",
        patterns=("cmake-build-*",),
        markers=("CMakeLists.txt",),
        regenerate="cmake --build .",
    ),
    # -- Editors / tooling ---------------------------------------------------
    Target(
        key="terraform",
        ecosystem="infra",
        patterns=(".terraform",),
        markers=("*.tf",),
        regenerate="terraform init",
    ),
    Target(
        key="gradle-wrapper-cache",
        ecosystem="jvm",
        patterns=(".gradle-cache",),
        regenerate="rebuilt by gradle on next run",
    ),
)


TARGETS_BY_KEY = {target.key: target for target in TARGETS}


def resolve(keys: Sequence[str]) -> tuple[Target, ...]:
    """Look up targets by key, raising ``KeyError`` on the first unknown one."""
    resolved = []
    for key in keys:
        try:
            resolved.append(TARGETS_BY_KEY[key])
        except KeyError:
            raise KeyError(key) from None
    return tuple(resolved)


def ecosystems() -> tuple[str, ...]:
    """Every ecosystem name, in first-seen order."""
    seen: list[str] = []
    for target in TARGETS:
        if target.ecosystem not in seen:
            seen.append(target.ecosystem)
    return tuple(seen)
