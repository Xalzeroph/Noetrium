from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.provenance import MethodSourceLane, MethodSourceLaneKind
from .source import SOURCE_LATER_RELEASED_QLASS_CODE, SOURCE_PAPER_ERA_REPOSITORY_STATE


@dataclass(frozen=True, slots=True)
class QlassAlfworldReleasedFidelity:
    """Later-released executable QLASS method fidelity.

    The February 2025 paper-era commit contains only release-intent documentation.
    It is provenance for the paper-era repository state, not executable method
    source. ALFWorld split/cardinality are owned exclusively by the typed benchmark
    cut and are intentionally not duplicated in this method fidelity object.
    """

    paper_source: MethodSourceLane = SOURCE_PAPER_ERA_REPOSITORY_STATE
    executable_source: MethodSourceLane = SOURCE_LATER_RELEASED_QLASS_CODE
    launcher_artifact: str = "qlass/scripts/eval_q_wo_perturb_7b_alfworld.sh"
    inference_artifact: str = "qlass/q_guided_inference.py"
    task_loader_artifact: str = "eval_agent/tasks/alfworld.py"
    base_model: str = "Llama-2-7b-chat-hf"
    policy_role: str = "sft_policy"
    q_value_role: str = "q_net"
    best_of_n: int = 2
    num_icl_examples: int = 1
    trajectories_per_task: int = 3
    launcher_slice_count: int = 4
    launcher_gpu_count: int = 4
    launcher_server_gpu_ids: tuple[int, ...] = (0, 1, 2, 3)
    launcher_eval_gpu_ids: tuple[int, ...] = (1, 2, 3, 4)
    launcher_model_name_variable: str = "explore_model_name"
    launcher_model_name_defined: bool = False
    launcher_runnable_as_written: bool = False
    max_turns_per_trajectory: int = 40
    sampling_mode: str = "bon"
    random_seed: int = 42
    force_first_icl: bool = True
    disable_perturbation: bool = True
    qnet_model_max_length: int = 4096
    branch_strategy: str = "reset_and_replay_committed_action_history"

    def __post_init__(self) -> None:
        if self.paper_source.kind is not MethodSourceLaneKind.PAPER_PROVENANCE:
            raise ValueError("QLASS paper-era repository state must remain paper provenance")
        if self.executable_source.kind is not MethodSourceLaneKind.LATER_RELEASED_EXECUTABLE:
            raise ValueError("QLASS executable cut must remain later-released executable")
        if self.paper_source.repository != self.executable_source.repository:
            raise ValueError("QLASS provenance lanes must bind the same audited repository")
        if self.paper_source.commit == self.executable_source.commit:
            raise ValueError("QLASS paper-era provenance and executable cuts must remain distinct")
        if (self.best_of_n, self.num_icl_examples, self.trajectories_per_task) != (2, 1, 3):
            raise ValueError("QLASS released best-of-N / ICL / trajectory configuration drifted")
        if (self.launcher_slice_count, self.launcher_gpu_count) != (4, 4):
            raise ValueError("QLASS released launcher partitioning drifted")
        if self.launcher_server_gpu_ids != (0, 1, 2, 3) or self.launcher_eval_gpu_ids != (1, 2, 3, 4):
            raise ValueError("QLASS released launcher GPU mapping drifted")
        if self.launcher_model_name_variable != "explore_model_name" or self.launcher_model_name_defined:
            raise ValueError("QLASS released launcher undefined model-name variable must remain explicit")
        if self.launcher_runnable_as_written:
            raise ValueError("QLASS released launcher must not be marked runnable as written")
        if self.max_turns_per_trajectory != 40 or self.random_seed != 42:
            raise ValueError("QLASS released inference budget/seed drifted")
        if self.sampling_mode != "bon" or not self.force_first_icl or not self.disable_perturbation:
            raise ValueError("QLASS released no-perturbation action-selection lane drifted")
        if self.branch_strategy != "reset_and_replay_committed_action_history":
            raise ValueError("QLASS candidate evaluation must retain reset-and-replay semantics")

    @property
    def committed_turn_budget(self) -> int:
        return self.trajectories_per_task * self.max_turns_per_trajectory


QLASS_ALFWORLD_RELEASED_FIDELITY = QlassAlfworldReleasedFidelity()

__all__ = [
    "QLASS_ALFWORLD_RELEASED_FIDELITY",
    "QlassAlfworldReleasedFidelity",
]
