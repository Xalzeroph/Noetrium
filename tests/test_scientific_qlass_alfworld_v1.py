from noetrium_platform.capabilities.environment.api import ActionRequest, ActionResult, ExecutionContext, Observation
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.benchmarks.alfworld import (
    ALFWORLD_QLASS_DEV_EXPECTED_TASK_COUNT,
    ALFWORLD_QLASS_DEV_REVISION,
    ALFWORLD_QLASS_DEV_SPLIT,
    ALFWORLD_TASK_FAMILIES,
    AlfworldTaskRecord,
    build_alfworld_qlass_dev_task_set,
)
from research.reproductions.qlass_alfworld import (
    QLASS_ALFWORLD_RELEASED_FIDELITY,
    build_qlass_alfworld_later_released_study,
    materialize_qlass_candidate_parent,
)


def _benchmark():
    records = tuple(
        AlfworldTaskRecord(
            gamefile=f"valid_seen/{ALFWORLD_TASK_FAMILIES[index % 6]}/task-{index:03d}/game.tw-pddl",
            family=ALFWORLD_TASK_FAMILIES[index % 6],
            content_digest=canonical_digest({"qlass-alfworld-task": index}),
        )
        for index in range(ALFWORLD_QLASS_DEV_EXPECTED_TASK_COUNT)
    )
    return build_alfworld_qlass_dev_task_set(
        records,
        source_digest=canonical_digest({"qlass-alfworld-source": 1}),
    )


def test_qlass_preserves_paper_provenance_vs_later_executable_source() -> None:
    fidelity = QLASS_ALFWORLD_RELEASED_FIDELITY
    assert fidelity.paper_source.kind.value == "paper_provenance"
    assert fidelity.executable_source.kind.value == "later_released_executable"
    assert fidelity.paper_source.commit != fidelity.executable_source.commit


def test_qlass_released_lane_freezes_dev_cut_and_q_guided_search() -> None:
    benchmark = _benchmark()
    study = build_qlass_alfworld_later_released_study(benchmark)
    assert benchmark.revision_id == ALFWORLD_QLASS_DEV_REVISION
    assert len(benchmark.selected_tasks(ALFWORLD_QLASS_DEV_SPLIT)) == 140
    assert study.execution_policy.trial_budget.max_steps == 120
    roles = {row.role: row.requirement_id for row in study.binding_requirements.model_roles}
    assert roles == {"policy": "model.qlass.sft-policy", "q_value": "model.qlass.q-net"}


def test_qlass_released_launcher_semantics_remain_exactly_separate_from_partitioning() -> None:
    fidelity = QLASS_ALFWORLD_RELEASED_FIDELITY
    assert (fidelity.best_of_n, fidelity.num_icl_examples, fidelity.trajectories_per_task) == (2, 1, 3)
    assert (fidelity.launcher_slice_count, fidelity.launcher_gpu_count) == (4, 4)
    assert fidelity.launcher_server_gpu_ids == (0, 1, 2, 3)
    assert fidelity.launcher_eval_gpu_ids == (1, 2, 3, 4)
    assert fidelity.launcher_model_name_variable == "explore_model_name"
    assert not fidelity.launcher_model_name_defined
    assert not fidelity.launcher_runnable_as_written
    assert fidelity.max_turns_per_trajectory == 40
    assert fidelity.branch_strategy == "reset_and_replay_committed_action_history"


class _QlassReplaySession:
    def __init__(self) -> None:
        self.actions: list[str] = []
        self.closed = False

    def observe(self, context):
        raise AssertionError("QLASS candidate replay should not observe implicitly")

    def act(self, request):
        self.actions.append(request.action_id)
        return ActionResult(
            request.action_id,
            True,
            Observation(f"obs:{request.action_id}", "qlass-replay", {}),
            None,
            {},
        )

    def reconcile(self, effect, context):
        raise AssertionError("QLASS candidate replay should not reconcile")

    def checkpoint(self):
        raise AssertionError("QLASS released lane reconstructs prefixes by reset and replay")

    def restore(self, payload):
        raise AssertionError("QLASS released lane reconstructs prefixes by reset and replay")

    def close(self) -> None:
        self.closed = True


def test_qlass_candidate_parent_reuses_platform_replay_composition() -> None:
    child = _QlassReplaySession()
    requests = (
        ActionRequest(
            "qlass-action-0",
            "text-action",
            {"text": "open fridge"},
            ExecutionContext("run", "trace", "span-0", task_id="alfworld:dev:7"),
        ),
    )
    session, receipt = materialize_qlass_candidate_parent(
        session_id="qlass:candidate:2",
        branch_id="candidate:2",
        source_cut_id="alfworld:dev:7:initial",
        task_id="alfworld:dev:7",
        committed_actions=requests,
        open_fresh=lambda _session_id: child,
    )
    assert session is child
    assert child.actions == ["qlass-action-0"]
    assert receipt.accepted_action_ids == ("qlass-action-0",)
