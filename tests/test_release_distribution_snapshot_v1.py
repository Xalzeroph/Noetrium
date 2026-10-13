from __future__ import annotations

from pathlib import Path

from scripts import release_distribution as release


def test_materialized_source_remains_valid_after_worktree_changes(tmp_path, monkeypatch) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='snapshot-fixture'\nversion='1.0.0'\nrequires-python='>=3.12'\n",
        encoding="utf-8",
    )
    payload = root / "payload.txt"
    payload.write_text("pinned-bytes", encoding="utf-8")
    monkeypatch.setattr(release, "ROOT", root)

    original_read_bytes = Path.read_bytes
    changed = False

    def read_bytes(path: Path) -> bytes:
        nonlocal changed
        raw = original_read_bytes(path)
        if path == payload and not changed:
            changed = True
            payload.write_text("concurrent-new-bytes", encoding="utf-8")
        return raw

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    destination = tmp_path / "snapshot"
    _digest, _count, manifest = release._materialize_exact_source(destination)

    assert changed is True
    assert payload.read_text(encoding="utf-8") == "concurrent-new-bytes"
    assert (destination / "payload.txt").read_text(encoding="utf-8") == "pinned-bytes"
    assert release.build_release_manifest(destination).digest() == manifest.digest()
