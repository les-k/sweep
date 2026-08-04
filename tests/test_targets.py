from __future__ import annotations

import pytest

from sweep.targets import TARGETS, TARGETS_BY_KEY, ecosystems, resolve


def match(key: str, name: str, siblings: set[str]) -> bool:
    return TARGETS_BY_KEY[key].matches(name, frozenset(siblings))


class TestMarkers:
    def test_node_modules_needs_a_package_json(self):
        assert match("node-modules", "node_modules", {"package.json", "src"})
        assert not match("node-modules", "node_modules", {"src"})

    def test_rust_target_needs_a_cargo_toml(self):
        assert match("rust-target", "target", {"Cargo.toml"})
        assert not match("rust-target", "target", {"README.md"})

    def test_same_name_different_ecosystems_are_told_apart_by_marker(self):
        # 'target' belongs to both cargo and maven; only the marker separates them.
        assert match("rust-target", "target", {"Cargo.toml"})
        assert not match("maven-target", "target", {"Cargo.toml"})
        assert match("maven-target", "target", {"pom.xml"})
        assert not match("rust-target", "target", {"pom.xml"})

    def test_pure_caches_need_no_marker(self):
        assert match("pycache", "__pycache__", set())
        assert match("ruff-cache", ".ruff_cache", set())

    def test_marker_globs_are_expanded(self):
        assert match("dotnet-build", "bin", {"Api.csproj"})
        assert match("dotnet-build", "obj", {"Solution.sln"})
        assert not match("dotnet-build", "bin", {"main.py"})

    def test_name_globs_are_expanded(self):
        assert match("python-build", "sweep.egg-info", {"pyproject.toml"})
        assert match("cmake-build", "cmake-build-debug", {"CMakeLists.txt"})


class TestCatalogue:
    def test_keys_are_unique(self):
        keys = [target.key for target in TARGETS]
        assert len(keys) == len(set(keys))

    def test_every_target_documents_how_to_regenerate_it(self):
        for target in TARGETS:
            assert target.regenerate, f"{target.key} has no regenerate hint"

    def test_generic_names_always_require_a_marker(self):
        """A bare 'build' or 'dist' must never match on name alone."""
        risky = {"build", "dist", "target", "bin", "obj", "venv"}
        for target in TARGETS:
            if risky & set(target.patterns):
                assert target.needs_marker, f"{target.key} matches {risky} unguarded"

    def test_resolve_returns_targets_in_order(self):
        assert [t.key for t in resolve(["pycache", "node-modules"])] == [
            "pycache",
            "node-modules",
        ]

    def test_resolve_raises_on_unknown_key(self):
        with pytest.raises(KeyError):
            resolve(["not-a-real-target"])

    def test_ecosystems_are_deduplicated(self):
        names = ecosystems()
        assert len(names) == len(set(names))
        assert "python" in names and "javascript" in names
