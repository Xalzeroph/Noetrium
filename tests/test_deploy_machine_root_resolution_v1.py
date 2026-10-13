from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "deploy" / "noetrium-paths.sh"


def _run(root: Path, *, env: dict[str, str] | None = None) -> str:
    command = f'. "{HELPER}"; noetrium_machine_state_root "$1"'
    completed = subprocess.run(
        ["/bin/sh", "-c", command, "noetrium-test", str(root)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    return completed.stdout.strip()


def test_linked_frozen_worktree_resolves_primary_machine_root(tmp_path: Path) -> None:
    repository = tmp_path / "noetrium"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.name", "Noetrium Test"], check=True)
    (repository / "deploy").mkdir()
    (repository / "deploy" / "noetrium").write_text("#!/bin/sh\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "deploy/noetrium"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "seed"], check=True)

    frozen = tmp_path / "frozen" / "noetrium"
    frozen.parent.mkdir()
    subprocess.run(
        ["git", "-C", str(repository), "worktree", "add", "-q", "--detach", str(frozen), "HEAD"],
        check=True,
    )

    expected = repository.resolve() / ".noetrium" / "machine"
    assert Path(_run(repository)) == expected
    assert Path(_run(frozen)) == expected


def test_explicit_machine_root_override_has_priority(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    explicit = tmp_path / "machine-authority"
    assert Path(_run(root, env={"NOETRIUM_MACHINE_STATE_ROOT": str(explicit)})) == explicit


def test_source_bundle_without_git_falls_back_to_its_noetrium_root(tmp_path: Path) -> None:
    root = tmp_path / "source-bundle"
    root.mkdir()
    assert Path(_run(root)) == root / ".noetrium" / "machine"
