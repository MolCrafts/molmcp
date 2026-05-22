"""Local source walking and snapshot-identity tests."""

from __future__ import annotations

from pathlib import Path

from molmcp.discovery.config import DiscoveryConfig
from molmcp.discovery.source.local import resolve_local_path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _config(tmp_path: Path, **kw) -> DiscoveryConfig:
    return DiscoveryConfig(cache_dir=tmp_path / "_cache", **kw)


def test_walk_respects_gitignore(tmp_path):
    _write(tmp_path / "a.py", "x = 1\n")
    _write(tmp_path / "ignored.py", "y = 2\n")
    _write(tmp_path / ".gitignore", "ignored.py\n")
    snap = resolve_local_path(tmp_path, str(tmp_path), _config(tmp_path))
    paths = {f.rel_path for f in snap.files}
    assert "a.py" in paths
    assert "ignored.py" not in paths


def test_walk_skips_large_files(tmp_path):
    _write(tmp_path / "small.py", "x = 1\n")
    _write(tmp_path / "big.py", "# " + "z" * 500 + "\n")
    snap = resolve_local_path(
        tmp_path, str(tmp_path), _config(tmp_path, max_file_bytes=100)
    )
    paths = {f.rel_path for f in snap.files}
    assert "small.py" in paths
    assert "big.py" not in paths


def test_default_excludes_skip_vendored_dirs(tmp_path):
    _write(tmp_path / "a.py", "x = 1\n")
    _write(tmp_path / "node_modules" / "lib.py", "z = 1\n")
    _write(tmp_path / "__pycache__" / "cached.py", "z = 2\n")
    snap = resolve_local_path(tmp_path, str(tmp_path), _config(tmp_path))
    paths = {f.rel_path for f in snap.files}
    assert "a.py" in paths
    assert all("node_modules" not in p for p in paths)
    assert all("__pycache__" not in p for p in paths)


def test_walk_recognizes_multiple_languages(tmp_path):
    _write(tmp_path / "mod.py", "x = 1\n")
    _write(tmp_path / "app.ts", "export const x = 1;\n")
    snap = resolve_local_path(tmp_path, str(tmp_path), _config(tmp_path))
    langs = {f.language for f in snap.files}
    assert langs == {"python", "typescript"}


def test_snapshot_id_is_stable_and_content_sensitive(tmp_path):
    target = tmp_path / "m.py"
    _write(target, "a = 1\n")
    cfg = _config(tmp_path)

    first = resolve_local_path(tmp_path, str(tmp_path), cfg)
    again = resolve_local_path(tmp_path, str(tmp_path), cfg)
    assert first.snapshot_id == again.snapshot_id

    target.write_text("a = 2\n", encoding="utf-8")
    changed = resolve_local_path(tmp_path, str(tmp_path), cfg)
    assert changed.snapshot_id != first.snapshot_id


def test_package_directory_uses_parent_as_root(tmp_path):
    pkg = tmp_path / "mypkg"
    _write(pkg / "__init__.py", "x = 1\n")
    _write(pkg / "core.py", "y = 2\n")
    snap = resolve_local_path(pkg, str(pkg), _config(tmp_path))
    paths = {f.rel_path for f in snap.files}
    # rel paths include the package name because root is the parent
    assert "mypkg/__init__.py" in paths
    assert "mypkg/core.py" in paths
