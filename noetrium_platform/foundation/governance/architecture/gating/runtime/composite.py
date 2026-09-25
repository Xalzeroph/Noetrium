from __future__ import annotations

from dataclasses import dataclass

from ..api import GateFinding, GatePort, GateReport, GateRequest, GateSeverity


class GateExecutionFailure(RuntimeError):
    """A child gate failed to produce a trustworthy report."""


@dataclass(frozen=True, slots=True)
class CompositeGate(GatePort):
    """A recursive gate node composed only from explicitly injected children.

    A parent does not discover global rules. It owns the set of child gates
    relevant to its boundary and preserves each child's report as provenance.
    """

    gate_id: str
    children: tuple[GatePort, ...] = ()

    def __post_init__(self) -> None:
        if not self.gate_id.strip():
            raise ValueError("gate_id must be non-empty")
        ids = tuple(child.gate_id for child in self.children)
        if len(set(ids)) != len(ids):
            raise ValueError("composite gate children must have unique gate ids")

    def evaluate(self, request: GateRequest) -> GateReport:
        reports: list[GateReport] = []
        findings: list[GateFinding] = []
        for child in self.children:
            try:
                report = child.evaluate(request)
            except Exception as exc:
                findings.append(
                    GateFinding(
                        self.gate_id,
                        GateSeverity.ERROR,
                        "GATE_CHILD_EXECUTION_FAILED",
                        f"child={child.gate_id} error_type={type(exc).__name__}",
                    )
                )
                continue
            reports.append(report)
        return GateReport(self.gate_id, tuple(findings), tuple(reports))


__all__ = ["CompositeGate", "GateExecutionFailure"]
