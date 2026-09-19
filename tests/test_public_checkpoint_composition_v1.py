from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


_DOWNSTREAM_SOURCE = '''
from pathlib import Path
import sys
from noetrium.contracts.research import RunCheckpointManifest
from noetrium.platform import build_project_run_checkpoint_store

root = Path(sys.argv[2])
manifest = RunCheckpointManifest(
    "checkpoint-public", "1", "experiment-digest", "run-public",
    "session-public", "cycle-public", "cycle-digest", (),
)
store = build_project_run_checkpoint_store(root)
if sys.argv[1] == "publish":
    saved = store.publish(manifest, ())
    assert saved == manifest
else:
    bundle = store.load(manifest.checkpoint_id)
    assert bundle.manifest == manifest
    assert bundle.manifest.digest() == manifest.digest()
    assert bundle.participant_payloads == ()
'''


def _run(script: Path, mode: str, root: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    repo = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = repo
    bootstrap = (
        "import runpy,sys; "
        "sys.path.insert(0,sys.argv[1]); "
        "script=sys.argv[2]; sys.argv=[script,*sys.argv[3:]]; "
        "runpy.run_path(script,run_name='__main__')"
    )
    return subprocess.run(
        [sys.executable, "-S", "-c", bootstrap, repo, str(script), mode, str(root)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )


def test_public_checkpoint_composition_survives_fresh_process_reopen(tmp_path: Path) -> None:
    script = tmp_path / "downstream_project.py"
    script.write_text(_DOWNSTREAM_SOURCE, encoding="utf-8")

    imports = tuple(
        node.module or ""
        for node in ast.walk(ast.parse(_DOWNSTREAM_SOURCE))
        if isinstance(node, ast.ImportFrom)
    )
    assert imports
    assert all(not module.startswith("noetrium_platform") for module in imports)
    assert set(imports) == {"pathlib", "noetrium.contracts.research", "noetrium.platform"}

    state_root = tmp_path / "project-state"
    published = _run(script, "publish", state_root)
    assert published.returncode == 0, published.stderr
    reopened = _run(script, "load", state_root)
    assert reopened.returncode == 0, reopened.stderr


def test_public_checkpoint_composition_rejects_noncanonical_manifest_bytes(tmp_path: Path) -> None:
    script = tmp_path / "downstream_project.py"
    script.write_text(_DOWNSTREAM_SOURCE, encoding="utf-8")
    state_root = tmp_path / "project-state"
    assert _run(script, "publish", state_root).returncode == 0

    safe = hashlib.sha256(b"checkpoint-public").hexdigest()
    manifest_path = state_root / "checkpoints" / "manifests" / f"{safe}.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    canonical = manifest_path.read_bytes()
    mutated = json.dumps(document, sort_keys=False, indent=2).encode("utf-8")
    assert mutated != canonical
    manifest_path.write_bytes(mutated)

    reopened = _run(script, "load", state_root)
    assert reopened.returncode != 0
    assert "manifest bytes are not canonical JSON" in reopened.stderr
