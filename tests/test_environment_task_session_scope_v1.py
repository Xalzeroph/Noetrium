
from __future__ import annotations

from contextlib import contextmanager

from noetrium_platform.capabilities.environment.api import (
    ActionRequest,
    ActionResult,
    EnvironmentCapabilityDescriptor,
    Observation,
)
from noetrium_platform.composition.environment_capabilities.lifetime import (
    LifetimeRoutedEnvironmentCapability,
)
from noetrium_platform.composition.local_research_execution_authority import (
    _EnvironmentTaskFinalizingWorkload,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


class _Session:
    def observe(self, context):
        return Observation("obs", "gen", {"task": context.task_id})

    def act(self, request: ActionRequest):
        return ActionResult(request.action_id, True, None, None, {})

    def reconcile(self, effect, context):
        return effect

    def close(self):
        return None


class _Authority:
    identity_digest = "1" * 64
    effect_recovery_durability = "crash_durable"

    def __init__(self):
        self.prepared = []
        self.opened = []
        self.released = []

    def capability_descriptors(self):
        return (
            EnvironmentCapabilityDescriptor(
                "minecraft.world",
                "1",
                action_types=("goto",),
            ),
        )

    def prepare(self, context):
        self.prepared.append((context.lifetime_id, context.task_id))

    def session_for(self, context):
        self.opened.append((context.lifetime_id, context.task_id))
        return _Session()

    def release(self, lifetime_id):
        self.released.append(lifetime_id)

    def close(self):
        return None


def _context(task_id=None):
    return ExecutionContext(
        run_id="run",
        trace_id="trace",
        span_id="span",
        study_id="study",
        condition_id="condition",
        assignment_seed="seed",
        repetition=0,
        lifetime_id="assignment-life",
        task_id=task_id,
        operation_id="op",
    )


def test_task_scope_routes_each_task_to_stable_distinct_environment_lifetime():
    authority = _Authority()
    capability = LifetimeRoutedEnvironmentCapability(
        authority,
        session_scope="task",
    )

    capability.prepare(_context())
    assert authority.prepared == []

    a = _context("task-a")
    b = _context("task-b")
    capability.prepare(a)
    capability.session_for(a)
    capability.session_for(a)
    capability.session_for(b)

    a_ids = {row[0] for row in authority.opened if row[1] == "task-a"}
    b_ids = {row[0] for row in authority.opened if row[1] == "task-b"}
    assert len(a_ids) == 1
    assert len(b_ids) == 1
    assert a_ids != b_ids
    assert next(iter(a_ids)).startswith("environment-task:")
    assert authority.prepared[0][0] == next(iter(a_ids))

    capability.release_context(a)
    assert authority.released == [next(iter(a_ids))]
    capability.release("assignment-life")
    assert authority.released[-1] == next(iter(b_ids))


def test_assignment_scope_preserves_one_environment_lifetime_across_tasks():
    authority = _Authority()
    capability = LifetimeRoutedEnvironmentCapability(
        authority,
        session_scope="assignment",
    )

    capability.prepare(_context())
    capability.session_for(_context("task-a"))
    capability.session_for(_context("task-b"))
    assert authority.prepared == [("assignment-life", None)]
    assert authority.opened == [
        ("assignment-life", None),
        ("assignment-life", None),
    ]


class _TaskDelegate:
    identity_digest = "2" * 64
    task_frontier_capacity = 4

    def __init__(self):
        self.calls = []

    @contextmanager
    def task_group_scope(self, context):
        yield None

    def execute_one(self, task, context):
        self.calls.append((task, context.task_id))
        return "result"


def test_task_finalizer_releases_even_when_workload_returns():
    authority = _Authority()
    capability = LifetimeRoutedEnvironmentCapability(
        authority,
        session_scope="task",
    )
    delegate = _TaskDelegate()
    workload = _EnvironmentTaskFinalizingWorkload(delegate, capability)
    context = _context("task-a")
    capability.session_for(context)

    assert workload.execute_one("task", context) == "result"
    assert len(authority.released) == 1
    assert workload.task_frontier_capacity == 4



def test_study_context_can_override_program_default_session_scope():
    authority = _Authority()
    capability = LifetimeRoutedEnvironmentCapability(
        authority,
        session_scope="assignment",
    )
    task_context = ExecutionContext(
        run_id="run",
        trace_id="trace",
        span_id="span",
        study_id="study-task",
        condition_id="condition",
        assignment_seed="seed",
        repetition=0,
        lifetime_id="assignment-life",
        task_id="task-a",
        operation_id="op",
        participant_context={"environment_session_scope": "task"},
    )
    assignment_context = ExecutionContext(
        run_id="run",
        trace_id="trace",
        span_id="span-2",
        study_id="study-assignment",
        condition_id="condition",
        assignment_seed="seed",
        repetition=0,
        lifetime_id="assignment-life-2",
        task_id="task-a",
        operation_id="op-2",
        participant_context={"environment_session_scope": "assignment"},
    )

    capability.session_for(task_context)
    capability.session_for(assignment_context)

    task_open, assignment_open = authority.opened
    assert task_open[0].startswith("environment-task:")
    assert task_open[1] == "task-a"
    assert assignment_open == ("assignment-life-2", None)


def test_random_seed_distinguishes_assignment_lifetimes():
    left = _context("task-a")
    right = ExecutionContext(
        run_id="run",
        trace_id="trace",
        span_id="span-right",
        study_id="study",
        condition_id="condition",
        assignment_seed="seed",
        repetition=0,
        lifetime_id="assignment-life-right",
        task_id="task-a",
        operation_id="op-right",
    )
    assert left.random_seed("world") != right.random_seed("world")


def test_task_routing_preserves_assignment_identity_for_seed_scoping():
    authority = _Authority()
    capability = LifetimeRoutedEnvironmentCapability(
        authority,
        session_scope="assignment",
    )
    context = ExecutionContext(
        run_id="run",
        trace_id="trace",
        span_id="span",
        study_id="study",
        condition_id="condition",
        assignment_seed="seed",
        repetition=0,
        lifetime_id="assignment-life",
        task_id="task-a",
        operation_id="op",
        participant_context={
            "environment_session_scope": "task",
            "environment_seed_scope": "assignment",
        },
    )
    routed = capability._routed_context(context)
    assert routed.lifetime_id != context.lifetime_id
    assert (
        routed.participant_context["environment_assignment_lifetime_id"]
        == "assignment-life"
    )
