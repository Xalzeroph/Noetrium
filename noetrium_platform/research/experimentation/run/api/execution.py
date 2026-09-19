from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import require_sha256
from noetrium_platform.research.experimentation.run.api.spec import ExperimentRunSpec
from noetrium_platform.research.experimentation.study.api import (
    BoundStudyExecutionPort,
    ExperimentPlan,
    StudyMatrixExecutionReport,
)


@dataclass(frozen=True, slots=True)
class ExperimentRunResult:
    """Run-owned envelope around execution of one authoritative ExperimentPlan."""

    run_spec_digest: str
    protocol_digest: str
    plan_digest: str
    binding_digest: str
    study_report: StudyMatrixExecutionReport

    def __post_init__(self) -> None:
        require_sha256(self.run_spec_digest, "experiment run result run_spec_digest")
        require_sha256(self.protocol_digest, "experiment run result protocol_digest")
        require_sha256(self.plan_digest, "experiment run result plan_digest")
        require_sha256(self.binding_digest, "experiment run result binding_digest")
        if self.study_report.protocol_digest != self.protocol_digest:
            raise ValueError("experiment run result protocol digest is inconsistent")
        if self.study_report.plan_digest != self.plan_digest:
            raise ValueError("experiment run result plan digest is inconsistent")
        if self.study_report.binding_digest != self.binding_digest:
            raise ValueError("experiment run result binding digest is inconsistent")


class ExperimentRunExecutionPort(Protocol):
    """Run-layer execution of one frozen, fully-bound scientific plan."""

    def execute(
        self,
        *,
        run_spec: ExperimentRunSpec,
        plan: ExperimentPlan,
        unit_adapter: BoundStudyExecutionPort,
    ) -> ExperimentRunResult: ...


__all__ = ["ExperimentRunExecutionPort", "ExperimentRunResult"]
