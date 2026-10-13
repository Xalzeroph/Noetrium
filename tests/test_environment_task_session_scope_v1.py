
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from noetrium_platform.capabilities.environment.api import (
    ActionRequest,
    ActionResult,
    EnvironmentCapabilityDescriptor,
    Observation,
)
from noetrium_platform.composition.environment_capabilities.lifetime import (
    LifetimeRoutedEnvironmentCapability,
)
from noetrium_platform.composition.environment_capability_runtime import (
    prepare_assignment_environment_trial,
    release_assignment_environment_trial,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    UNBOUNDED_EXECUTION_CONTROL,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, freeze_json
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    ReplayLevel,
    assignment_workload,
    assignment_workload_task_ids,
    study_assignment,
    study_assignment_workload,
    task_unit,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    execution_policy_unit,
    intervention_unit,
)


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
        self.prepared_contexts = []
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

    def prepare(self, context, control):
        control.checkpoint()
        self.prepared.append((context.lifetime_id, context.task_id))
        self.prepared_contexts.append(context)

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

    capability.prepare(_context(), UNBOUNDED_EXECUTION_CONTROL)
    assert authority.prepared == []

    a = _context("task-a")
    b = _context("task-b")
    capability.prepare(a, UNBOUNDED_EXECUTION_CONTROL)
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

    capability.prepare(_context(), UNBOUNDED_EXECUTION_CONTROL)
    capability.session_for(_context("task-a"))
    capability.session_for(_context("task-b"))
    assert authority.prepared == [("assignment-life", None)]
    assert authority.opened == [
        ("assignment-life", None),
        ("assignment-life", None),
    ]


def test_task_scope_release_callback_closes_exact_routed_lifetime():
    authority = _Authority()
    capability = LifetimeRoutedEnvironmentCapability(
        authority,
        session_scope="task",
    )
    context = _context("task-a")
    capability.session_for(context)
    capability.release_context(context)
    assert len(authority.released) == 1
    assert authority.released[0].startswith("environment-task:")

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

def _prewarm_request(*, session_scope: str, seed_scope: str, setups):
    task_ids = tuple(f"task-{index}" for index in range(len(setups)))
    definitions = tuple(
        task_unit(
            task_ids[index],
            revision_id="1",
            family="environment-session-scope-test",
            schema_id="environment-session-scope-test.v1",
            content_digest=None,
            content={
                "objective": f"objective-{index}",
                **({} if setup is None else {"environment_setup": setup}),
            },
        )
        for index, setup in enumerate(setups)
    )
    workload = assignment_workload(task_ids)
    assignment = study_assignment(
        "study",
        "variant",
        0,
        0,
        "seed",
        workload,
    )
    return SimpleNamespace(
        experiment_id="experiment",
        run_id="run",
        request_digest="a" * 64,
        execution_context=_context(),
        assignment=assignment,
        intervention_spec=intervention_unit("control", ()),
        participant_schedule_spec=None,
        execution_policy=execution_policy_unit(
            replay_level=ReplayLevel.OBSERVATIONAL,
            environment_session_scope=session_scope,
            environment_seed_scope=seed_scope,
        ),
        project_id="project",
        assignment_lifetime_id="assignment-life",
        task_definitions=definitions,
    )


def test_trial_prewarm_preserves_exact_assignment_environment_setup():
    authority = _Authority()
    capability = LifetimeRoutedEnvironmentCapability(
        authority,
        session_scope="assignment",
    )
    setup = {
        "minecraft": {"biome": "snowy_plains", "weather": "clear"},
        "pairing_id": "pairing-1",
    }

    prepare_assignment_environment_trial(
        capability,
        _prewarm_request(
            session_scope="assignment",
            seed_scope="assignment",
            setups=(setup, setup),
        ),
        UNBOUNDED_EXECUTION_CONTROL,
    )

    assert len(authority.prepared) == 1
    prepared_context = authority.prepared_contexts[0]
    assert prepared_context.participant_context["environment_task_setup"] == setup
    assert prepared_context.participant_context["environment_pairing_id"] == "pairing-1"
    assert prepared_context.participant_context["environment_session_scope"] == "assignment"
    assert prepared_context.participant_context["environment_seed_scope"] == "assignment"
    assert prepared_context.trace_id == "trace"
    assert prepared_context.parent_span_id == "span"
    assert prepared_context.span_id.startswith("trial-prewarm:")
    assert prepared_context.task_id is None


def test_trial_prewarm_task_scope_uses_first_task_exact_setup():
    authority = _Authority()
    capability = LifetimeRoutedEnvironmentCapability(
        authority,
        session_scope="task",
    )
    first = {"minecraft": {"biome": "plains"}, "pairing_id": "first"}
    second = {"minecraft": {"biome": "taiga"}, "pairing_id": "second"}

    request = _prewarm_request(
        session_scope="task",
        seed_scope="assignment",
        setups=(first, second),
    )
    prepare_assignment_environment_trial(
        capability,
        request,
        UNBOUNDED_EXECUTION_CONTROL,
    )

    prepared_context = authority.prepared_contexts[0]
    expected_task = assignment_workload_task_ids(
        study_assignment_workload(request.assignment)
    )[0]
    setup_by_task = {"task-0": first, "task-1": second}
    assert prepared_context.task_id == expected_task
    assert prepared_context.participant_context["environment_task_setup"] == setup_by_task[expected_task]
    assert prepared_context.participant_context["environment_pairing_id"] == setup_by_task[expected_task]["pairing_id"]


def test_assignment_scope_rejects_task_setup_drift_before_prewarm():
    authority = _Authority()
    capability = LifetimeRoutedEnvironmentCapability(
        authority,
        session_scope="assignment",
    )

    import pytest
    with pytest.raises(ValueError, match="one invariant environment_setup"):
        prepare_assignment_environment_trial(
            capability,
            _prewarm_request(
                session_scope="assignment",
                seed_scope="assignment",
                setups=(
                    {"minecraft": {"biome": "plains"}},
                    {"minecraft": {"biome": "taiga"}},
                ),
            ),
            UNBOUNDED_EXECUTION_CONTROL,
        )
    assert authority.prepared == []

def test_assignment_trial_release_function_releases_assignment_lifetime():
    authority = _Authority()
    capability = LifetimeRoutedEnvironmentCapability(
        authority,
        session_scope="assignment",
    )
    request = _prewarm_request(
        session_scope="assignment",
        seed_scope="assignment",
        setups=(None,),
    )
    capability.session_for(request.execution_context)
    release_assignment_environment_trial(capability, request)
    assert authority.released == ["assignment-life"]
