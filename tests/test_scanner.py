from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from conftest import write
from sweep.scanner import PRUNE_ALWAYS, Find, delete, measure, scan, walk
from sweep.targets import TARGETS_BY_KEY


def keys(finds) -> set[str]:
    return {find.target.key for find in finds}


class TestWalk:
    def test_finds_the_real_artifacts(self, workspace: Path):
        finds = list(walk(workspace))
        assert keys(finds) == {"node-modules", "rust-target", "pycache"}

    def test_leaves_unmarked_lookalikes_alone(self, workspace: Path):
        found = {find.path for find in walk(workspace)}
        assert workspace / "decoy" / "node_modules" not in found
        assert workspace / "docs" / "target" not in found

    def test_does_not_descend_into_a_match(self, workspace: Path):
        """node_modules contains its own package.json; it must not be re-matched inside."""
        finds = [f for f in walk(workspace) if f.target.key == "node-modules"]
        assert [f.path for f in finds] == [workspace / "web" / "node_modules"]

    def test_respects_max_depth(self, workspace: Path):
        # __pycache__ lives at depth 2 (workspace/lib/__pycache__).
        assert "pycache" in keys(walk(workspace, max_depth=None))
        assert "pycache" not in keys(walk(workspace, max_depth=0))

    def test_exclude_glob_matches_on_name_or_full_path(self, workspace: Path):
        assert "rust-target" not in keys(walk(workspace, exclude=["target"]))
        assert "node-modules" not in keys(walk(workspace, exclude=[str(workspace / "web" / "*")]))

    def test_target_filter_narrows_the_search(self, workspace: Path):
        only_python = [TARGETS_BY_KEY["pycache"]]
        assert keys(walk(workspace, targets=only_python)) == {"pycache"}

    def test_skips_vcs_directories(self, tmp_path: Path):
        write(tmp_path / ".git" / "modules" / "x" / "__pycache__" / "a.pyc")
        assert list(walk(tmp_path)) == []
        assert ".git" in PRUNE_ALWAYS

    def test_unreadable_root_does_not_raise(self, tmp_path: Path):
        assert list(walk(tmp_path / "does-not-exist")) == []


class TestMeasure:
    def test_sums_nested_file_sizes(self, workspace: Path):
        find = next(f for f in walk(workspace) if f.target.key == "node-modules")
        measure(find)
        assert find.size == 300  # 100 + 200
        assert find.files == 2
        assert find.unreadable == 0

    def test_counts_a_vanished_directory_as_unreadable(self, tmp_path: Path):
        target = tmp_path / "__pycache__"
        target.mkdir()
        find = Find(path=target, target=TARGETS_BY_KEY["pycache"])
        target.rmdir()
        measure(find)
        assert find.size == 0
        assert find.unreadable == 1

    @pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks require privileges on Windows")
    def test_does_not_follow_symlinks_out_of_the_tree(self, tmp_path: Path):
        outside = write(tmp_path / "outside" / "huge.bin", 5000)
        cache = tmp_path / "proj" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "link").symlink_to(outside.parent, target_is_directory=True)

        find = next(f for f in walk(tmp_path / "proj"))
        measure(find)

        # Neither the 5000 bytes behind the link nor the link's own inode count:
        # deleting a symlink reclaims nothing, so reporting it as space would lie.
        assert find.size == 0
        assert find.files == 0
        assert (outside).exists()  # and the target is still there afterwards

    @pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks require privileges on Windows")
    def test_does_not_walk_through_a_symlinked_directory(self, tmp_path: Path):
        """A link pointing at a real project must not produce a find."""
        real = tmp_path / "elsewhere"
        write(real / "package.json", 2)
        write(real / "node_modules" / "dep.js", 100)

        (tmp_path / "proj").mkdir()
        (tmp_path / "proj" / "linked").symlink_to(real, target_is_directory=True)

        assert list(walk(tmp_path / "proj")) == []


class TestScan:
    def test_totals_across_every_find(self, workspace: Path):
        result = scan([workspace])
        assert result.total_size == 300 + 500 + 40
        assert result.total_files == 4
        assert result.directories_visited > 0

    def test_results_are_sorted_largest_first(self, workspace: Path):
        sizes = [find.size for find in scan([workspace]).finds]
        assert sizes == sorted(sizes, reverse=True)

    def test_min_size_filters_out_the_small_ones(self, workspace: Path):
        result = scan([workspace], min_size=400)
        assert keys(result.finds) == {"rust-target"}

    def test_older_than_filters_on_mtime(self, workspace: Path):
        long_ago = time.time() - 100 * 86_400
        stale = workspace / "lib" / "__pycache__"
        os.utime(stale, (long_ago, long_ago))

        assert keys(scan([workspace], older_than=30).finds) == {"pycache"}
        assert scan([workspace], older_than=200).finds == []

    def test_roots_are_resolved_to_absolute_paths(self, workspace: Path):
        result = scan([workspace])
        assert result.roots[0].is_absolute()

    def test_multiple_roots_are_combined(self, workspace: Path):
        result = scan([workspace / "web", workspace / "rust"])
        assert keys(result.finds) == {"node-modules", "rust-target"}


class TestFind:
    def test_age_is_reported_in_days(self, workspace: Path):
        find = Find(
            path=workspace,
            target=TARGETS_BY_KEY["pycache"],
            mtime=time.time() - 3 * 86_400,
        )
        assert 2.9 < find.age_days < 3.1

    def test_missing_mtime_reads_as_zero(self, workspace: Path):
        assert Find(path=workspace, target=TARGETS_BY_KEY["pycache"]).age_days == 0.0

    def test_project_is_the_owning_directory(self, workspace: Path):
        find = next(f for f in walk(workspace) if f.target.key == "node-modules")
        assert find.project == workspace / "web"


class TestDelete:
    def test_removes_the_tree(self, workspace: Path):
        find = next(f for f in walk(workspace) if f.target.key == "node-modules")
        delete(find)
        assert not find.path.exists()
        assert (workspace / "web" / "package.json").exists()  # project itself untouched

    def test_removes_read_only_files(self, tmp_path: Path):
        cache = tmp_path / "__pycache__"
        locked = write(cache / "locked.pyc")
        locked.chmod(0o444)

        delete(Find(path=cache, target=TARGETS_BY_KEY["pycache"]))
        assert not cache.exists()

    def test_raises_when_the_path_is_gone(self, tmp_path: Path):
        find = Find(path=tmp_path / "nope", target=TARGETS_BY_KEY["pycache"])
        with pytest.raises(OSError):
            delete(find)
