from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import noetrium_platform.foundation.governance.gate.composition as gate_composition
from noetrium_platform.foundation.governance.gate.api import GateFinding, GateReport, GateRequest, GateSeverity
from noetrium_platform.foundation.governance.gate.composition import build_platform_gate
from noetrium_platform.foundation.governance.gate.runtime import CompositeGate


@dataclass(frozen=True, slots=True)
class FixedGate:
    gate_id: str
    findings: tuple[GateFinding, ...] = ()

    def evaluate(self, request: GateRequest) -> GateReport:
        return GateReport(self.gate_id, self.findings)


def test_parent_gate_preserves_injected_child_reports_and_provenance(tmp_path: Path) -> None:
    child = FixedGate(
        "project.local",
        (GateFinding("project.local", GateSeverity.ERROR, "PROJECT_RULE", "failed"),),
    )
    report = CompositeGate("project", (child,)).evaluate(
        GateRequest("project", tmp_path)
    )
    assert not report.passed
    assert report.children[0].gate_id == "project.local"
    assert report.all_findings[0].code == "PROJECT_RULE"


def test_child_exception_is_fail_closed_without_secret_or_traceback(tmp_path: Path) -> None:
    class ExplodingGate:
        gate_id = "broken"

        def evaluate(self, request: GateRequest) -> GateReport:
            raise RuntimeError("token=must-not-escape")

    report = CompositeGate("root", (ExplodingGate(),)).evaluate(
        GateRequest("root", tmp_path)
    )
    assert not report.passed
    assert report.findings[0].code == "GATE_CHILD_EXECUTION_FAILED"
    assert "must-not-escape" not in report.findings[0].detail


def test_platform_gate_is_explicitly_composable(tmp_path: Path) -> None:
    report = build_platform_gate(
        root=tmp_path,
        children=(FixedGate("custom.project"),),
    ).evaluate(GateRequest("repository", tmp_path))
    assert report.gate_id == "governance"
    assert {child.gate_id for child in report.children} == {
        "governance.architecture",
        "custom.project",
    }

def test_architecture_gate_source_failure_is_explicit_error_not_exception_or_false_green(
    tmp_path: Path, monkeypatch,
) -> None:
    secret = "token=must-not-escape-from-architecture-source-failure"

    def fail_report(_root: Path):
        raise RuntimeError(secret)

    monkeypatch.setattr(gate_composition, "build_architecture_report", fail_report)
    report = gate_composition.ArchitectureReportGate().evaluate(
        GateRequest("repository", tmp_path)
    )
    assert not report.passed
    assert report.gate_id == "governance.architecture"
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.severity is GateSeverity.ERROR
    assert finding.code == "ARCHITECTURE_SOURCE_UNAVAILABLE"
    assert finding.detail == "error_type=RuntimeError"
    assert secret not in finding.detail
