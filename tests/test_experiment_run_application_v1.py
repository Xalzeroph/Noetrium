from __future__ import annotations

from types import SimpleNamespace

import pytest

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_digest
from noetrium_platform.research.experimentation.run.api import ExperimentRunSpec
from noetrium_platform.research.experimentation.run.runtime import ExperimentRunApplication
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.experimentation.run.runtime.decision_runtime import (
    DecisionCycleRuntime,
)
from noetrium_platform.research.experimentation.run.runtime.resources import RunResourceAcquirer
from noetrium_platform.research.experimentation.study.api import (
    ExperimentPlan,
    StudyConcurrencyPolicy,
    StudyMetricObservation,
    StudyProtocol,
    StudyVariantSpec,
    VariantBinding,
    VariantKind,
)
from noetrium_platform.research.experimentation.study.runtime import (
    BasicStudyMetricAggregator,
    DeterministicStudyAssignment,
)


class _Publication:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def publish_protocol(self, protocol, assignments):
        del protocol, assignments
        self.calls.append("protocol")
        return "protocol"

    def publish_observations(self, observations):
        del observations
        self.calls.append("observations")
        return "observations"

    def publish_aggregates(self, aggregates):
        del aggregates
        self.calls.append("aggregates")
        return "aggregates"


class _BoundAdapter:
    def execute_bound(self, unit, bindings, plan_digest):
        del bindings, plan_digest
        return tuple(
            StudyMetricObservation(
                assignment,
                (("score", float(unit.repetition + 1)),),
            )
            for assignment in unit.assignments
        )

    def execute_bound_variant(self, assignment, binding, plan_digest):
        del binding, plan_digest
        return StudyMetricObservation(assignment, (("score", 1.0),))


def _plan() -> ExperimentPlan:
    protocol = StudyProtocol(
        study_id="study-1",
        workload_id="workload-1",
        variants=(
            StudyVariantSpec("control", VariantKind.CONTROL, "fixed", "a" * 64),
            StudyVariantSpec("treatment", VariantKind.TREATMENT, "candidate", "b" * 64),
        ),
        repetitions=2,
        seed_schedule_digest="c" * 64,
        metric_names=("score",),
        task_manifest_digest="d" * 64,
        budget_tiers=("standard",),
        concurrency_policy=StudyConcurrencyPolicy.serial_shared_v1(
            repetition_timeout_seconds=3600.0
        ),
    )
    assignments = DeterministicStudyAssignment().assignments(protocol)
    bindings = tuple(
        VariantBinding(
            variant,
            "e" * 64,
            f"provider-{variant.variant_id}",
            "none",
            variant.kind.value,
        )
        for variant in protocol.variants
    )
    return ExperimentPlan.compile(protocol, bindings, assignments)


def test_run_parent_executes_and_publishes_only_compiled_plan() -> None:
    plan = _plan()
    protocol = plan.protocol
    run_spec = ExperimentRunSpec(
        run_id="run-1",
        project_id="project-1",
        experiment_id="experiment-1",
        study_id=protocol.study_id,
        execution_profile="test",
        task_manifest_digest=protocol.task_manifest_digest,
        seed_schedule_digest=protocol.seed_schedule_digest,
        repetitions=protocol.repetitions,
        artifact_root="runs/run-1",
        environment_identity_digest=canonical_digest("environment"),
    )
    publication = _Publication()
    application = ExperimentRunApplication(
        aggregation=BasicStudyMetricAggregator(),
        publication=publication,
    )

    result = application.execute(
        run_spec=run_spec,
        plan=plan,
        unit_adapter=_BoundAdapter(),
    )

    assert result.run_spec_digest == run_spec.identity_digest()
    assert result.protocol_digest == plan.protocol_digest
    assert result.plan_digest == plan.plan_digest
    assert result.binding_digest == plan.binding_digest
    assert len(result.study_report.observations) == 4
    assert publication.calls == ["protocol", "observations", "aggregates"]


def test_experiment_run_rejects_non_plan_before_execution() -> None:
    application = ExperimentRunApplication(
        aggregation=BasicStudyMetricAggregator(),
        publication=object(),
    )
    with pytest.raises(TypeError, match="ExperimentPlan"):
        application.execute(
            run_spec=object(),
            plan=SimpleNamespace(),
            unit_adapter=object(),
        )


class _NoneBinder:
    def bind(self, spec, context):
        return None


class _EmptyBinder:
    def bind(self, spec, context):
        return SimpleNamespace(operation_results=(), participants=())


class _NoopLifecycle:
    def open_participant(self, *args, **kwargs):
        raise AssertionError("participant lifecycle must not run")

    def close_participant(self, *args, **kwargs):
        raise AssertionError("participant lifecycle must not run")


class _NoneScientific:
    def execute(self, **kwargs):
        return None


def _context() -> ExecutionContext:
    return ExecutionContext("run", "trace", "span", study_id="study")


def _cycle_identity() -> DecisionCycleIdentity:
    return DecisionCycleIdentity(
        "run",
        "cycle",
        "session",
        "task",
        "trace",
    )


def _cycle_spec():
    return SimpleNamespace(
        study_id="study",
        identity_digest=lambda: "a" * 64,
    )


def test_run_resource_acquirer_rejects_missing_binding_explicitly() -> None:
    acquirer = RunResourceAcquirer(_NoneBinder(), _NoopLifecycle())
    identity = SimpleNamespace(run_id="run", trace_id="trace", session_id="session")
    spec = SimpleNamespace(study_id="study")
    with pytest.raises(RuntimeError, match="binder returned no bound participants"):
        acquirer.acquire(spec, identity)


def test_decision_cycle_runtime_rejects_missing_binding_through_machine() -> None:
    runtime = DecisionCycleRuntime(
        _NoneBinder(),
        _NoopLifecycle(),
        _NoneScientific(),
    )
    with pytest.raises(RuntimeError, match="binder returned no participants"):
        runtime.run(
            _cycle_spec(),
            _cycle_identity(),
            task=object(),
            input_kind="test",
            input_payload=None,
        )


def test_decision_cycle_runtime_rejects_missing_trial_execution_explicitly() -> None:
    runtime = DecisionCycleRuntime(
        _EmptyBinder(),
        _NoopLifecycle(),
        _NoneScientific(),
    )
    with pytest.raises(TypeError, match="invalid TrialCycleExecution"):
        runtime.run(
            _cycle_spec(),
            _cycle_identity(),
            task=object(),
            input_kind="test",
            input_payload=None,
        )
