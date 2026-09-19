from __future__ import annotations

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.research.experimentation.api.program import (
    ExperimentProgramBinding,
    compile_experiment_program,
)
from noetrium_platform.research.experimentation.run.api import (
    ExperimentRunExecutionPort,
    ExperimentRunResult,
)
from noetrium_platform.research.experimentation.run.api.spec import ExperimentRunSpec
from noetrium_platform.research.experimentation.study.api import (
    BoundStudyExecutionPort,
    ExperimentPlan,
    StudyArtifactPublicationPort,
    StudyMetricAggregationPort,
)


class ExperimentRunApplication(ExperimentRunExecutionPort):
    """Run parent over one frozen ExperimentPlan and its ExperimentProgram."""

    def __init__(
        self,
        *,
        aggregation: StudyMetricAggregationPort,
        publication: StudyArtifactPublicationPort,
        task_group: TaskGroupPort | None = None,
    ) -> None:
        if not callable(getattr(aggregation, "aggregate", None)):
            raise TypeError("experiment run requires StudyMetricAggregationPort")
        self._aggregation = aggregation
        self._publication = publication
        self._task_group = task_group

    def execute(
        self,
        *,
        run_spec: ExperimentRunSpec,
        plan: ExperimentPlan,
        unit_adapter: BoundStudyExecutionPort,
    ) -> ExperimentRunResult:
        if type(plan) is not ExperimentPlan:
            raise TypeError("experiment run requires ExperimentPlan")
        if not isinstance(unit_adapter, BoundStudyExecutionPort):
            raise TypeError("experiment run requires BoundStudyExecutionPort")
        plan.assert_consistent()
        protocol = plan.protocol
        self._validate_run_identity(run_spec, protocol)

        self._publication.publish_protocol(protocol, plan.assignments)
        compiled = compile_experiment_program(plan)
        report = ExperimentProgramBinding(
            compiled,
            unit_adapter,
            self._aggregation,
            task_group=self._task_group,
        ).execute(
            machine_id=f"experiment-run:{run_spec.identity_digest()[:24]}",
        )
        self._publication.publish_observations(report.observations)
        self._publication.publish_aggregates(report.aggregates)
        return ExperimentRunResult(
            run_spec_digest=run_spec.identity_digest(),
            protocol_digest=plan.protocol_digest,
            plan_digest=plan.plan_digest,
            binding_digest=plan.binding_digest,
            study_report=report,
        )

    @staticmethod
    def _validate_run_identity(
        run_spec: ExperimentRunSpec,
        protocol,
    ) -> None:
        if run_spec.study_id != protocol.study_id:
            raise ValueError("experiment run specification belongs to another study")
        if run_spec.task_manifest_digest != protocol.task_manifest_digest:
            raise ValueError("experiment run task digest does not match study protocol")
        if run_spec.seed_schedule_digest != protocol.seed_schedule_digest:
            raise ValueError("experiment run seed digest does not match study protocol")
        if run_spec.repetitions != protocol.repetitions:
            raise ValueError("experiment run repetition count does not match study protocol")


__all__ = ["ExperimentRunApplication"]
