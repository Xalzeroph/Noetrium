from __future__ import annotations

from dataclasses import dataclass


VOYAGER_AUDITED_COMMIT = "55e45a880755d0c8c66ca7fb5fe7962ac8974f89"


@dataclass(frozen=True, slots=True)
class VoyagerMinecraftFidelity:
    paper_uri: str = "https://arxiv.org/abs/2305.16291"
    source_repository: str = "https://github.com/MineDojo/Voyager"
    audited_commit: str = VOYAGER_AUDITED_COMMIT
    source_artifact: str = "voyager/voyager.py"
    automatic_curriculum: bool = True
    executable_skill_library: bool = True
    skill_retrieval: bool = True
    iterative_program_improvement: bool = True
    improvement_feedback: tuple[str, ...] = (
        "environment_feedback",
        "execution_errors",
        "self_verification",
    )
    model_parameter_finetuning: bool = False
    learning_resume_from_checkpoint: bool = True
    inference_can_load_skill_library_without_resume: bool = True
    task_decomposition_before_inference: bool = True

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("Voyager audited commit must be a git SHA")
        if not all((
            self.automatic_curriculum,
            self.executable_skill_library,
            self.skill_retrieval,
            self.iterative_program_improvement,
        )):
            raise ValueError("Voyager three-component method semantics drifted")
        if self.improvement_feedback != (
            "environment_feedback",
            "execution_errors",
            "self_verification",
        ):
            raise ValueError("Voyager iterative prompting feedback drifted")
        if self.model_parameter_finetuning:
            raise ValueError("paper-era Voyager uses black-box model queries, not parameter fine-tuning")
        if not self.learning_resume_from_checkpoint:
            raise ValueError("Voyager learning checkpoint resume semantics drifted")
        if not self.inference_can_load_skill_library_without_resume:
            raise ValueError("Voyager learned-skill inference semantics drifted")
        if not self.task_decomposition_before_inference:
            raise ValueError("Voyager task decomposition semantics drifted")


VOYAGER_MINECRAFT_FIDELITY = VoyagerMinecraftFidelity()


__all__ = ["VOYAGER_AUDITED_COMMIT", "VOYAGER_MINECRAFT_FIDELITY", "VoyagerMinecraftFidelity"]
