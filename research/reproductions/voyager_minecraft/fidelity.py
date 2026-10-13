from __future__ import annotations

from dataclasses import dataclass


VOYAGER_AUDITED_COMMIT = "edeee8383a22b96b54bff51c6cf809306a7b34a3"
VOYAGER_COMPATIBILITY_COMMIT = "55e45a880755d0c8c66ca7fb5fe7962ac8974f89"


@dataclass(frozen=True, slots=True)
class VoyagerMinecraftFidelity:
    paper_uri: str = "https://mlanthology.org/tmlr/2024/wang2024tmlr-voyager/"
    source_repository: str = "https://github.com/MineDojo/Voyager"
    audited_commit: str = VOYAGER_AUDITED_COMMIT
    compatibility_commit: str = VOYAGER_COMPATIBILITY_COMMIT
    source_artifact: str = "voyager/voyager.py"

    automatic_curriculum: bool = True
    executable_skill_library: bool = True
    skill_retrieval: bool = True
    iterative_program_improvement: bool = True
    critic_self_verification: bool = True

    max_learning_iterations: int = 160
    action_task_max_retries: int = 4
    critic_parse_max_retries: int = 5
    skill_retrieval_top_k: int = 5
    initial_curriculum_task: str = "Mine 1 wood log"
    initial_difficulty: str = "peaceful"
    post_warmup_difficulty: str = "easy"
    post_warmup_completed_task_threshold: int = 15
    curriculum_context_warmup: int = 15
    curriculum_random_section_probability: float = 0.8
    curriculum_qa_semantic_reuse_distance_threshold: float = 0.05
    curriculum_qa_context_answer_limit: int = 5

    improvement_feedback: tuple[str, ...] = (
        "environment_feedback",
        "execution_errors",
        "self_verification",
    )
    skill_record_fields: tuple[str, ...] = (
        "program_name",
        "program_code",
        "skill_description",
    )
    skill_retrieval_query_sources: tuple[str, ...] = (
        "task_context",
        "execution_chat_summary",
    )
    persistent_memory_families: tuple[str, ...] = (
        "skill_library",
        "chest_memory",
        "curriculum_completed_tasks",
        "curriculum_failed_tasks",
        "curriculum_qa_cache",
    )

    model_parameter_finetuning: bool = False
    learning_resume_from_checkpoint: bool = True
    inference_uses_learned_skill_library: bool = True
    inference_task_decomposition: bool = True
    successful_rollout_adds_skill: bool = True
    failed_rollout_does_not_add_skill: bool = True
    hard_reset_first_learning_session: bool = True
    soft_reset_resume_learning_session: bool = True

    def __post_init__(self) -> None:
        for value in (self.audited_commit, self.compatibility_commit):
            if len(value) != 40:
                raise ValueError("Voyager source commit must be a git SHA")
        if self.audited_commit == self.compatibility_commit:
            raise ValueError("Voyager paper and compatibility cuts must differ")
        if not all((
            self.automatic_curriculum,
            self.executable_skill_library,
            self.skill_retrieval,
            self.iterative_program_improvement,
            self.critic_self_verification,
        )):
            raise ValueError("Voyager core method semantics drifted")
        if (
            self.max_learning_iterations,
            self.action_task_max_retries,
            self.critic_parse_max_retries,
            self.skill_retrieval_top_k,
            self.post_warmup_completed_task_threshold,
        ) != (160, 4, 5, 5, 15):
            raise ValueError("Voyager paper-era control bounds drifted")
        if self.initial_curriculum_task != "Mine 1 wood log":
            raise ValueError("Voyager initial curriculum task drifted")
        if self.curriculum_context_warmup != 15:
            raise ValueError("Voyager curriculum QA warm-up drifted")
        if self.curriculum_random_section_probability != 0.8:
            raise ValueError(
                "Voyager curriculum random inclusion probability drifted"
            )
        if self.curriculum_qa_semantic_reuse_distance_threshold != 0.05:
            raise ValueError(
                "Voyager curriculum QA semantic reuse threshold drifted"
            )
        if self.curriculum_qa_context_answer_limit != 5:
            raise ValueError(
                "Voyager curriculum QA context answer limit drifted"
            )
        if (self.initial_difficulty, self.post_warmup_difficulty) != (
            "peaceful",
            "easy",
        ):
            raise ValueError("Voyager learning difficulty schedule drifted")
        if self.improvement_feedback != (
            "environment_feedback",
            "execution_errors",
            "self_verification",
        ):
            raise ValueError("Voyager iterative prompting feedback drifted")
        if self.skill_record_fields != (
            "program_name",
            "program_code",
            "skill_description",
        ):
            raise ValueError("Voyager skill record schema drifted")
        if self.skill_retrieval_query_sources != (
            "task_context",
            "execution_chat_summary",
        ):
            raise ValueError("Voyager skill retrieval query semantics drifted")
        if self.model_parameter_finetuning:
            raise ValueError(
                "paper-era Voyager uses black-box model queries, not parameter fine-tuning"
            )
        if not all((
            self.learning_resume_from_checkpoint,
            self.inference_uses_learned_skill_library,
            self.inference_task_decomposition,
            self.successful_rollout_adds_skill,
            self.failed_rollout_does_not_add_skill,
            self.hard_reset_first_learning_session,
            self.soft_reset_resume_learning_session,
        )):
            raise ValueError("Voyager lifecycle semantics drifted")


VOYAGER_MINECRAFT_FIDELITY = VoyagerMinecraftFidelity()


__all__ = [
    "VOYAGER_AUDITED_COMMIT",
    "VOYAGER_COMPATIBILITY_COMMIT",
    "VOYAGER_MINECRAFT_FIDELITY",
    "VoyagerMinecraftFidelity",
]
