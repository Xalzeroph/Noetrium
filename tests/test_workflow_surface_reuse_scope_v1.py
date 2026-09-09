from __future__ import annotations

from noetrium_platform.research.execution.workflow.api import (
    TrialCycleExecution,
    WorkflowSurfaceBindingContext,
    WorkflowSurfaceReuseScope,
    workflow_surface_reuse_scope,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.capabilities.participant.core.api import BoundParticipants
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentTrialCycleExecutor


class _DefaultFactory:
    surface_id = "default.surface.v1"

    def bind(self, context: WorkflowSurfaceBindingContext) -> object:
        del context
        return object()


class _RunFactory(_DefaultFactory):
    reuse_scope = "run"


def test_unknown_surface_factories_are_cycle_scoped() -> None:
    assert workflow_surface_reuse_scope(_DefaultFactory()) is WorkflowSurfaceReuseScope.CYCLE


def test_surface_factory_can_explicitly_opt_into_run_scope() -> None:
    assert workflow_surface_reuse_scope(_RunFactory()) is WorkflowSurfaceReuseScope.RUN


class _Protocol:
    protocol_id = "reuse-test.v1"
    surface_id = "reuse-test.surface.v1"

    def run(self, surface, context, *, task, input_kind, input_payload):
        del surface, task, input_kind, input_payload
        return TrialCycleExecution("", None, context, ())


class _CountingFactory:
    surface_id = _Protocol.surface_id

    def __init__(self, reuse_scope: str | None = None) -> None:
        self.bind_count = 0
        if reuse_scope is not None:
            self.reuse_scope = reuse_scope

    def bind(self, context: WorkflowSurfaceBindingContext) -> object:
        del context
        self.bind_count += 1
        return object()


def _execute_twice(factory: _CountingFactory) -> None:
    executor = ExperimentTrialCycleExecutor(
        object(), _Protocol(), workflow_surface_factories=(factory,)
    )
    bound = BoundParticipants(())
    executor.execute(
        bound=bound,
        participant_sessions=(),
        context=ExecutionContext("run-1", "trace", "span-1", decision_cycle_id="cycle-1"),
        task=None,
        input_kind="input",
        input_payload=None,
    )
    executor.execute(
        bound=bound,
        participant_sessions=(),
        context=ExecutionContext("run-1", "trace", "span-2", decision_cycle_id="cycle-2"),
        task=None,
        input_kind="input",
        input_payload=None,
    )


def test_run_scoped_surface_is_bound_once_per_run() -> None:
    factory = _CountingFactory("run")
    _execute_twice(factory)
    assert factory.bind_count == 1


def test_default_cycle_surface_is_bound_for_each_cycle() -> None:
    factory = _CountingFactory()
    _execute_twice(factory)
    assert factory.bind_count == 2
