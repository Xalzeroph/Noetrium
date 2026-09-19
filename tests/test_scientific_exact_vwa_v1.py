from __future__ import annotations

from noetrium_platform.capabilities.environment.api import ActionRequest, ActionResult, ExecutionContext, Observation
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.benchmarks.visualwebarena import (
    VISUALWEBARENA_SITE_TASK_COUNTS,
    VisualWebArenaTaskRecord,
    build_visualwebarena_site_task_set,
)
from research.reproductions.exact_vwa import (
    EXACT_VWA_FIDELITY,
    build_exact_vwa_classifieds_study,
    materialize_exact_candidate_parent,
)


def _digest(index: int) -> str:
    return canonical_digest({"benchmark": "exact-vwa-classifieds", "index": index})


def _cut():
    count = VISUALWEBARENA_SITE_TASK_COUNTS["classifieds"]
    return build_visualwebarena_site_task_set(
        "classifieds",
        tuple(VisualWebArenaTaskRecord("classifieds", index, _digest(index)) for index in range(count)),
        source_digest=canonical_digest({"source": "official-vwa-classifieds"}),
    )


def test_exact_released_classifieds_cut_and_rmcts_budget_are_frozen() -> None:
    benchmark = _cut()
    study = build_exact_vwa_classifieds_study(benchmark)
    assert len(benchmark.tasks) == VISUALWEBARENA_SITE_TASK_COUNTS["classifieds"] == 234
    assert study.execution_policy.trial_budget.max_steps == 5
    assert study.execution_policy.trial_budget.max_seconds == 1500.0
    assert EXACT_VWA_FIDELITY.branching_factor == 5
    assert EXACT_VWA_FIDELITY.value_function_budget == 20
    assert EXACT_VWA_FIDELITY.max_reflections_per_task == 3
    assert EXACT_VWA_FIDELITY.tasks_per_environment_reset == 8
    assert EXACT_VWA_FIDELITY.environment_branch_strategy == "reset_and_replay_action_history"


def test_exact_exposes_four_scientific_model_roles_without_collapsing_same_gpt4o_model() -> None:
    study = build_exact_vwa_classifieds_study(_cut())
    assert tuple((row.role, row.requirement_id) for row in study.binding_requirements.model_roles) == (
        ("embedding", "model.exact.embedding"),
        ("policy", "model.exact.policy"),
        ("reflection", "model.exact.reflection"),
        ("value", "model.exact.value"),
    )
    requirements = study.binding_requirements.participants[0].capability_requirement_ids
    assert "environment.branch-state" not in requirements
    assert "environment.act" in requirements
    assert "environment.reset" in requirements


class _ExactReplaySession:
    def __init__(self) -> None:
        self.actions: list[str] = []
        self.closed = False

    def observe(self, context):
        raise AssertionError("ExACT replay should not observe implicitly")

    def act(self, request):
        self.actions.append(request.action_id)
        return ActionResult(
            request.action_id,
            True,
            Observation(f"obs:{request.action_id}", "exact-replay", {}),
            None,
            {},
        )

    def reconcile(self, effect, context):
        raise AssertionError("ExACT replay should not reconcile")

    def checkpoint(self):
        raise AssertionError("ExACT released VWA lane is replay-based, not checkpoint-based")

    def restore(self, payload):
        raise AssertionError("ExACT released VWA lane is replay-based, not checkpoint-based")

    def capture_branch_state(self, context):
        raise AssertionError("ExACT released VWA lane does not use portable BranchState")

    def restore_branch_state(self, state, context):
        raise AssertionError("ExACT released VWA lane does not use portable BranchState")

    def close(self) -> None:
        self.closed = True


def test_exact_candidate_parent_uses_reset_and_ordered_action_replay() -> None:
    child = _ExactReplaySession()
    task_id = "vwa:classifieds:7"
    requests = (
        ActionRequest(
            "exact-action-0",
            "browser-action",
            {"action": "click"},
            ExecutionContext("run", "trace", "span-0", task_id=task_id),
        ),
        ActionRequest(
            "exact-action-1",
            "browser-action",
            {"action": "type"},
            ExecutionContext("run", "trace", "span-1", task_id=task_id),
        ),
    )
    session, receipt = materialize_exact_candidate_parent(
        session_id="exact:candidate:2",
        branch_id="candidate:2",
        source_cut_id="vwa:classifieds:7:initial",
        task_id=task_id,
        committed_actions=requests,
        open_fresh=lambda _session_id: child,
    )

    assert session is child
    assert child.actions == ["exact-action-0", "exact-action-1"]
    assert receipt.accepted_action_ids == tuple(child.actions)
    assert receipt.action_request_digests == tuple(
        canonical_digest(
            {
                "action_id": request.action_id,
                "action_type": request.action_type,
                "payload": request.payload,
                "run_id": request.context.run_id,
                "study_id": request.context.study_id,
                "lifetime_id": request.context.lifetime_id,
                "task_id": request.context.task_id,
                "decision_cycle_id": request.context.decision_cycle_id,
                "checkpoint_id": request.context.checkpoint_id,
                "source_generation": request.context.generation("environment"),
            }
        )
        for request in requests
    )
