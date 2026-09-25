import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hierarchical_reachability_has_no_orphan_or_boundary_bypass() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "audit_entrypoint_reachability.py"),
            "--strict",
            "--json",
            str(ROOT / ".reachability-test.json"),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    try:
        report = json.loads((ROOT / ".reachability-test.json").read_text())
    finally:
        (ROOT / ".reachability-test.json").unlink(missing_ok=True)
    assert report["schema"] == "noetrium.hierarchical-reachability-audit.v3"
    assert report["parse_error_count"] == 0
    assert report["orphan_count"] == 0
    assert report["layer_member_attachment_missing_count"] == 0
    assert report["sideplane_attachment_missing_count"] == 0
    assert report["unified_api_lower_layer_source_count"] == 0
    assert result.returncode == 0, result.stdout + result.stderr
