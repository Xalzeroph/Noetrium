from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from noetrium_platform.foundation.governance.architecture.composition import build_architecture_report

from ..api import GateFinding, GatePort, GateReport, GateRequest, GateSeverity
from ..runtime import CompositeGate


class ArchitectureReportGate(GatePort):
    """Adapter that exposes the existing architecture analyzer through GatePort."""

    gate_id = "governance.architecture"

    def evaluate(self, request: GateRequest) -> GateReport:
        try:
            report = build_architecture_report(Path(request.root))
        except Exception as exc:
            return GateReport(
                self.gate_id,
                (GateFinding(
                    self.gate_id,
                    GateSeverity.ERROR,
                    "ARCHITECTURE_SOURCE_UNAVAILABLE",
                    f"error_type={type(exc).__name__}",
                ),),
            )
        findings: list[GateFinding] = []
        for violation in report.import_violations:
            findings.append(GateFinding(self.gate_id, GateSeverity.ERROR, "IMPORT_BOUNDARY", str(asdict(violation))))
        for violation in report.layer_violations:
            findings.append(GateFinding(self.gate_id, GateSeverity.ERROR, "LAYER_DAG", str(asdict(violation))))
        for cycle in report.package_cycles:
            findings.append(GateFinding(self.gate_id, GateSeverity.ERROR, "PACKAGE_CYCLE", " -> ".join(cycle)))
        for violation in report.declared_authority_violations:
            findings.append(GateFinding(self.gate_id, GateSeverity.ERROR, "DECLARED_AUTHORITY", str(asdict(violation))))
        for violation in report.source_invariant_violations:
            findings.append(GateFinding(self.gate_id, GateSeverity.ERROR, "SOURCE_INVARIANT", str(asdict(violation))))
        for violation in report.source_authority_violations:
            findings.append(GateFinding(self.gate_id, GateSeverity.ERROR, "SOURCE_AUTHORITY", str(asdict(violation))))
        for violation in report.architecture_budget_violations:
            findings.append(GateFinding(self.gate_id, GateSeverity.ERROR, "ARCHITECTURE_BUDGET", str(asdict(violation))))
        return GateReport(self.gate_id, tuple(findings))


def build_platform_gate(*, root: Path, children: tuple[GatePort, ...] = ()) -> GatePort:
    """Compose the platform gate from explicit child gates.

    The architecture gate is the current default child. Quality, security,
    release and project-local gates can be supplied by a parent composition
    root without modifying this provider or introducing a registry lookup.
    """

    return CompositeGate(
        "governance",
        (ArchitectureReportGate(), *children),
    )


__all__ = ["ArchitectureReportGate", "build_platform_gate"]
