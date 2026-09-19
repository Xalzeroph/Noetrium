from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.project_root import discover_project_root
from noetrium_platform.foundation.governance.gate.api import GateRequest
from noetrium_platform.foundation.governance.gate.composition import build_platform_gate

def main() -> int:
    root = discover_project_root(__file__)
    report = build_platform_gate(root=root).evaluate(
        GateRequest(subject_id="repository", root=root)
    )
    for finding in report.all_findings:
        print(f"FAIL {finding.code} {finding.gate_id}: {finding.detail}")
    if not report.passed:
        return 1
    print("ARCHITECTURE_GATE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
