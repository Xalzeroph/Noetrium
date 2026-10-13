import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hierarchical_reachability_has_no_orphan_or_boundary_bypass(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "audit_entrypoint_reachability.py"),
            "--strict",
            "--json",
            str(tmp_path / "reachability.json"),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    report_path = tmp_path / "reachability.json"
    assert report_path.is_file(), result.stdout + result.stderr
    report = json.loads(report_path.read_text())
    assert report["schema"] == "noetrium.hierarchical-reachability-audit.v3"
    assert report["parse_error_count"] == 0
    assert report["orphan_count"] == 0
    assert report["layer_member_attachment_missing_count"] == 0
    assert report["sideplane_attachment_missing_count"] == 0
    assert report["unified_api_lower_layer_source_count"] == 0
    assert result.returncode == 0, result.stdout + result.stderr
