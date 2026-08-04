from __future__ import annotations

from pathlib import Path

import pytest


def write(path: Path, size: int = 10) -> Path:
    """Create a file of exactly ``size`` bytes, making parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A directory tree with one real find of each interesting shape.

    Layout::

        workspace/
          web/                     <- node project, node_modules is reclaimable
            package.json
            src/index.js
            node_modules/left-pad/index.js   (300 bytes total)
          rust/                    <- cargo project, target/ is reclaimable
            Cargo.toml
            target/debug/app       (500 bytes)
          decoy/                   <- no package.json, so node_modules stays
            node_modules/vendor.js
          docs/                    <- a hand-written target/, no Cargo.toml
            target/notes.md
          lib/__pycache__/m.pyc    <- pure cache, no marker needed (40 bytes)
    """
    root = tmp_path / "workspace"

    write(root / "web" / "package.json", 2)
    write(root / "web" / "src" / "index.js", 20)
    write(root / "web" / "node_modules" / "left-pad" / "index.js", 100)
    write(root / "web" / "node_modules" / "left-pad" / "package.json", 200)

    write(root / "rust" / "Cargo.toml", 5)
    write(root / "rust" / "target" / "debug" / "app", 500)

    write(root / "decoy" / "node_modules" / "vendor.js", 999)

    write(root / "docs" / "target" / "notes.md", 999)

    write(root / "lib" / "__pycache__" / "m.pyc", 40)

    return root
