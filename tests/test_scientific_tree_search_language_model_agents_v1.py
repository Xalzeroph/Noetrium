from __future__ import annotations

from noetrium_platform.capabilities.environment.api import ActionRequest, ActionResult, ExecutionContext, Observation
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.benchmarks.visualwebarena import (
    VISUALWEBARENA_SITE_TASK_COUNTS,
    VisualWebArenaTaskRecord,
    build_visualwebarena_site_task_set,
)
from research.reproductions.tree_search_language_model_agents import (
    TREE_SEARCH_VWA_FIDELITY,
    build_tree_search_vwa_shopping_released_study,
    materialize_tree_search_branch_prefix,
)


def _cut():
    count = VISUALWEBARENA_SITE_TASK_COUNTS["shopping"]
    return build_visualwebarena_site_task_set(
        "shopping",
        tuple(
            VisualWebArenaTaskRecord(
                "shopping", index, canonical_digest({"vwa-shopping": index})
            )
            for index in range(count)
        ),
        source_digest=canonical_digest({"source": "official-vwa-shopping"}),
    )


def test_tree_search_released_lane_freezes_466_task_search_contract() -> None:
    benchmark = _cut()
    study = build_tree_search_vwa_shopping_released_study(benchmark)
    assert len(benchmark.tasks) == 466
    assert study.execution_policy.trial_budget.max_steps == 5
    assert TREE_SEARCH_VWA_FIDELITY.max_depth == 4
    assert TREE_SEARCH_VWA_FIDELITY.lookahead_steps == 5
    assert TREE_SEARCH_VWA_FIDELITY.branching_factor == 5
    assert TREE_SEARCH_VWA_FIDELITY.value_function_budget == 20
    assert TREE_SEARCH_VWA_FIDELITY.launcher_reset_batch_size == 5
    assert TREE_SEARCH_VWA_FIDELITY.environment_branch_strategy == "reset_and_replay_action_history"


def test_tree_search_exposes_policy_value_and_evaluation_model_roles() -> None:
    study = build_tree_search_vwa_shopping_released_study(_cut())
    roles = tuple((row.role, row.requirement_id) for row in study.binding_requirements.model_roles)
    assert roles == (
        ("evaluation_captioner", "model.visualwebarena.evaluation-captioner"),
        ("policy", "model.tree-search.policy"),
        ("value", "model.tree-search.value"),
    )
    capabilities = study.binding_requirements.participants[0].capability_requirement_ids
    assert "environment.act" in capabilities
    assert "environment.branch-state" not in capabilities


class _ReplaySession:
    def __init__(self) -> None:
        self.actions: list[str] = []
        self.closed = False

    def observe(self, context):
        raise AssertionError("branch prefix materialization should not observe implicitly")

    def act(self, request):
        self.actions.append(request.action_id)
        return ActionResult(
            request.action_id,
            True,
            Observation(f"obs:{request.action_id}", "vwa-replay", {}),
            None,
            {},
        )

    def reconcile(self, effect, context):
        raise AssertionError("branch prefix materialization should not reconcile")

    def checkpoint(self):
        raise AssertionError("Tree Search released lane is replay-based, not checkpoint-based")

    def restore(self, payload):
        raise AssertionError("Tree Search released lane is replay-based, not checkpoint-based")

    def close(self) -> None:
        self.closed = True


def test_tree_search_branch_materialization_reuses_platform_replay_composition() -> None:
    child = _ReplaySession()
    requests = (
        ActionRequest(
            "tree-action-0",
            "browser-action",
            {"action": "click"},
            ExecutionContext("run", "trace", "span-0", task_id="vwa:shopping:7"),
        ),
        ActionRequest(
            "tree-action-1",
            "browser-action",
            {"action": "type"},
            ExecutionContext("run", "trace", "span-1", task_id="vwa:shopping:7"),
        ),
    )
    session, receipt = materialize_tree_search_branch_prefix(
        session_id="tree-search:branch:2",
        branch_id="branch:2",
        source_cut_id="vwa:shopping:7:initial",
        task_id="vwa:shopping:7",
        committed_actions=requests,
        open_fresh=lambda _session_id: child,
    )
    assert session is child
    assert child.actions == ["tree-action-0", "tree-action-1"]
    assert receipt.accepted_action_ids == tuple(child.actions)
