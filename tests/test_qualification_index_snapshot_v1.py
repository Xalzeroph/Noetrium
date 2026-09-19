from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.capabilities.model.qualification.providers.qualification_index_snapshot import (
    TargetPackageIndexSnapshotProbe,
    decode_snapshot_output,
)


def test_snapshot_probe_executes_standalone_target_worker() -> None:
    calls = []

    def run(argv, timeout):
        calls.append((argv, timeout))
        return 0, json.dumps({
            "root_candidates": [
                {"version": "1.2.3", "compatible": True, "error": None}
            ]
        }), ""

    probe = TargetPackageIndexSnapshotProbe(run)
    result = probe.capture(
        Path("/opt/env/bin/python"),
        "vllm",
        "https://pypi.org/simple",
        ("1.2.3",),
        3.0,
        fallback_index="https://pypi.org/simple",
        root_candidates=("1.2.3",),
    )

    argv, timeout = calls[0]
    assert timeout == 3.0
    assert argv[0] == str(Path("/opt/env/bin/python"))
    assert Path(argv[1]).name == "qualification_index_worker.py"
    assert argv[1] != "-c"
    assert result["root_candidates"][0]["compatible"] is True


def test_snapshot_decoder_rejects_string_boolean() -> None:
    result = decode_snapshot_output(json.dumps({
        "selected_version": "1.2.3",
        "artifacts": [],
        "dependency_nodes": [],
        "dependency_closure_complete": "false",
        "dependency_closure_error": None,
        "error": None,
    }))
    assert result["dependency_closure_complete"] is False
    assert "must be boolean" in str(result["error"])


def test_snapshot_decoder_rejects_unknown_artifact_fields() -> None:
    result = decode_snapshot_output(json.dumps({
        "selected_version": "1.2.3",
        "artifacts": [{
            "filename": "pkg-1.2.3-py3-none-any.whl",
            "version": "1.2.3",
            "kind": "wheel",
            "unexpected": "value",
        }],
        "dependency_nodes": [],
        "dependency_closure_complete": True,
        "dependency_closure_error": None,
        "error": None,
    }))
    assert result["dependency_closure_complete"] is False
    assert "artifact fields are invalid" in str(result["error"])
