from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sweep.cli import main, parse_size, select_targets
from sweep.formatting import Palette, human_age, human_size, shorten


class TestParseSize:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("512", 512),
            ("1k", 1024),
            ("1KB", 1024),
            ("10 MB", 10 * 1024**2),
            ("1.5G", int(1.5 * 1024**3)),
            ("2tb", 2 * 1024**4),
        ],
    )
    def test_accepts_the_usual_spellings(self, text, expected):
        assert parse_size(text) == expected

    @pytest.mark.parametrize("text", ["", "big", "10 zebibytes", "-5MB", "MB"])
    def test_rejects_nonsense(self, text):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_size(text)


class TestSelectTargets:
    def test_only_narrows_to_the_named_kinds(self):
        chosen = select_targets(only=["pycache"], skip=[], eco=[])
        assert [t.key for t in chosen] == ["pycache"]

    def test_skip_removes_kinds(self):
        chosen = select_targets(only=[], skip=["pycache"], eco=[])
        assert "pycache" not in {t.key for t in chosen}

    def test_ecosystem_filters_by_group(self):
        chosen = select_targets(only=[], skip=[], eco=["rust"])
        assert {t.ecosystem for t in chosen} == {"rust"}

    def test_skip_wins_over_only(self):
        with pytest.raises(SystemExit):
            select_targets(only=["pycache"], skip=["pycache"], eco=[])

    def test_unknown_key_is_a_friendly_error(self):
        with pytest.raises(SystemExit, match="unknown target"):
            select_targets(only=["nope"], skip=[], eco=[])

    def test_unknown_ecosystem_is_a_friendly_error(self):
        with pytest.raises(SystemExit, match="unknown ecosystem"):
            select_targets(only=[], skip=[], eco=["cobol"])


class TestFormatting:
    @pytest.mark.parametrize(
        "size,expected",
        [
            (0, "0 B"),
            (999, "999 B"),
            (1024, "1.0 KB"),
            (1536, "1.5 KB"),
            (20 * 1024, "20 KB"),
            (1024**3, "1.0 GB"),
        ],
    )
    def test_human_size(self, size, expected):
        assert human_size(size) == expected

    @pytest.mark.parametrize(
        "days,expected",
        [(0.2, "today"), (1.5, "1 day"), (10, "10 days"), (90, "3 months")],
    )
    def test_human_age(self, days, expected):
        assert human_age(days) == expected

    def test_shorten_keeps_the_tail(self):
        assert shorten("/a/very/long/path/to/node_modules", 20).endswith("node_modules")
        assert len(shorten("/a/very/long/path/to/node_modules", 20)) == 20

    def test_shorten_leaves_short_paths_alone(self):
        assert shorten("/a/b", 20) == "/a/b"

    def test_palette_is_a_no_op_when_disabled(self):
        assert Palette(enabled=False).green("x") == "x"
        assert "\033[" in Palette(enabled=True).green("x")


class TestMain:
    def test_dry_run_reports_without_deleting(self, workspace: Path, capsys):
        assert main([str(workspace), "--no-color"]) == 0
        out = capsys.readouterr().out

        assert "node-modules" in out
        assert "840 B reclaimable" in out
        assert "Re-run with --delete" in out
        assert (workspace / "web" / "node_modules").exists()

    def test_json_output_is_parseable(self, workspace: Path, capsys):
        assert main([str(workspace), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["total_size_bytes"] == 840
        assert payload["total_files"] == 4
        assert {find["kind"] for find in payload["finds"]} == {
            "node-modules",
            "rust-target",
            "pycache",
        }
        assert all(find["regenerate_with"] for find in payload["finds"])

    def test_delete_with_yes_removes_everything_found(self, workspace: Path, capsys):
        assert main([str(workspace), "--delete", "--yes", "--no-color"]) == 0
        out = capsys.readouterr().out

        assert "Reclaimed 840 B" in out
        assert not (workspace / "web" / "node_modules").exists()
        assert not (workspace / "rust" / "target").exists()
        # Sources and unmarked lookalikes survive.
        assert (workspace / "web" / "src" / "index.js").exists()
        assert (workspace / "decoy" / "node_modules").exists()

    def test_declining_the_prompt_deletes_nothing(self, workspace: Path, capsys, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "n")
        assert main([str(workspace), "--delete", "--no-color"]) == 0

        assert "Cancelled." in capsys.readouterr().out
        assert (workspace / "web" / "node_modules").exists()

    def test_accepting_the_prompt_deletes(self, workspace: Path, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "y")
        assert main([str(workspace), "--delete", "--no-color"]) == 0
        assert not (workspace / "web" / "node_modules").exists()

    def test_a_clean_tree_reports_nothing_to_do(self, tmp_path: Path, capsys):
        (tmp_path / "src").mkdir()
        assert main([str(tmp_path), "--no-color"]) == 0
        assert "Nothing to reclaim" in capsys.readouterr().out

    def test_min_size_is_applied(self, workspace: Path, capsys):
        assert main([str(workspace), "--min-size", "400", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert {find["kind"] for find in payload["finds"]} == {"rust-target"}

    def test_missing_directory_exits_two(self, tmp_path: Path, capsys):
        assert main([str(tmp_path / "nope")]) == 2
        assert "is not a directory" in capsys.readouterr().err

    def test_list_targets_documents_every_kind(self, capsys):
        assert main(["--list-targets", "--no-color"]) == 0
        out = capsys.readouterr().out
        assert "node-modules" in out
        assert "needs package.json alongside" in out
        assert "always safe (pure cache)" in out

    def test_limit_truncates_the_listing(self, workspace: Path, capsys):
        assert main([str(workspace), "--limit", "1", "--no-color"]) == 0
        out = capsys.readouterr().out
        assert "and 2 more" in out
