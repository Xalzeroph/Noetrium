from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest


AFLOW_PAPER_ERA_COMMIT = "072839af7f75948d91d3784154128ab2456831f0"
AFLOW_REVIEW_REVISION_COMMIT = "d01051abc612ba9c6c284e9827c0b7091cb83d87"


@dataclass(frozen=True, slots=True)
class AFlowFidelity:
    """Paper-era AFlow workflow-search contract.

    The formal executable lane is the MetaGPT AFlow source cut labelled
    Final version on 2024-10-24. Later MetaGPT review changes and the
    standalone 2025 repository are separate provenance lanes.
    """

    paper_uri: str = (
        "https://proceedings.iclr.cc/paper_files/paper/2025/hash/"
        "5492ecbce4439401798dcd2c90be94cd-Abstract-Conference.html"
    )
    source_repository: str = "https://github.com/FoundationAgents/MetaGPT"
    audited_commit: str = AFLOW_PAPER_ERA_COMMIT
    review_revision_commit: str = AFLOW_REVIEW_REVISION_COMMIT

    datasets: tuple[str, ...] = (
        "HumanEval", "MBPP", "GSM8K", "MATH", "HotpotQA", "DROP",
    )
    search_object: str = "python_workflow_source"
    workflow_representation: str = "code"
    initial_round: int = 1
    optimization_iterations: int = 20
    maximum_materialized_round: int = 21

    parent_pool_size: int = 4
    force_initial_round_into_parent_pool: bool = True
    score_scale: float = 100.0
    softmax_alpha: float = 0.2
    uniform_mix_weight: float = 0.3
    score_softmax_weight: float = 0.7

    experience_conditioned_generation: bool = True
    success_rule: str = "child_mean_score_gt_parent_mean_score"
    sampled_failure_log_count: int = 3

    validation_repetitions: int = 5
    test_repetitions: int = 3
    validation_suffix: str = "_validate.jsonl"
    test_suffix: str = "_test.jsonl"

    convergence_top_k: int = 3
    convergence_z: float = 0.0
    convergence_consecutive_rounds: int = 5
    convergence_enabled_by_default: bool = True

    optimizer_model: str = "claude-3-5-sonnet-20240620"
    execution_model: str = "gpt-4o-mini"
    humaneval_question_type: str = "code"
    humaneval_operators: tuple[str, ...] = (
        "Custom", "CustomCodeGenerate", "ScEnsemble", "Test",
    )

    parent_sampling_explicitly_seeded: bool = False
    failure_log_sampling_explicitly_seeded: bool = False
    generated_workflow_is_untrusted_code: bool = True

    @property
    def fidelity_digest(self) -> str:
        return canonical_digest({
            "audited_commit": self.audited_commit,
            "datasets": self.datasets,
            "search_object": self.search_object,
            "workflow_representation": self.workflow_representation,
            "initial_round": self.initial_round,
            "optimization_iterations": self.optimization_iterations,
            "maximum_materialized_round": self.maximum_materialized_round,
            "parent_pool_size": self.parent_pool_size,
            "force_initial_round_into_parent_pool": self.force_initial_round_into_parent_pool,
            "score_scale": self.score_scale,
            "softmax_alpha": self.softmax_alpha,
            "uniform_mix_weight": self.uniform_mix_weight,
            "score_softmax_weight": self.score_softmax_weight,
            "experience_conditioned_generation": self.experience_conditioned_generation,
            "success_rule": self.success_rule,
            "sampled_failure_log_count": self.sampled_failure_log_count,
            "validation_repetitions": self.validation_repetitions,
            "test_repetitions": self.test_repetitions,
            "convergence_top_k": self.convergence_top_k,
            "convergence_z": self.convergence_z,
            "convergence_consecutive_rounds": self.convergence_consecutive_rounds,
            "optimizer_model": self.optimizer_model,
            "execution_model": self.execution_model,
            "humaneval_operators": self.humaneval_operators,
            "parent_sampling_explicitly_seeded": self.parent_sampling_explicitly_seeded,
            "failure_log_sampling_explicitly_seeded": self.failure_log_sampling_explicitly_seeded,
        })

    def __post_init__(self) -> None:
        if self.audited_commit != AFLOW_PAPER_ERA_COMMIT or len(self.audited_commit) != 40:
            raise ValueError("AFlow formal lane must bind the full paper-era MetaGPT SHA")
        if self.datasets != ("HumanEval", "MBPP", "GSM8K", "MATH", "HotpotQA", "DROP"):
            raise ValueError("AFlow six-dataset experiment set drifted")
        if (self.search_object, self.workflow_representation) != ("python_workflow_source", "code"):
            raise ValueError("AFlow searches code-represented workflows")
        if (self.initial_round, self.optimization_iterations, self.maximum_materialized_round) != (1, 20, 21):
            raise ValueError("AFlow paper-era round semantics drifted")
        if (self.parent_pool_size, self.score_scale, self.softmax_alpha, self.uniform_mix_weight, self.score_softmax_weight) != (4, 100.0, 0.2, 0.3, 0.7):
            raise ValueError("AFlow parent sampling semantics drifted")
        if not self.force_initial_round_into_parent_pool:
            raise ValueError("AFlow parent pool must retain round one")
        if (not self.experience_conditioned_generation or self.success_rule != "child_mean_score_gt_parent_mean_score" or self.sampled_failure_log_count != 3):
            raise ValueError("AFlow experience semantics drifted")
        if (self.validation_repetitions, self.test_repetitions, self.validation_suffix, self.test_suffix) != (5, 3, "_validate.jsonl", "_test.jsonl"):
            raise ValueError("AFlow evaluation protocol drifted")
        if (self.convergence_top_k, self.convergence_z, self.convergence_consecutive_rounds, self.convergence_enabled_by_default) != (3, 0.0, 5, True):
            raise ValueError("AFlow convergence semantics drifted")
        if (self.optimizer_model, self.execution_model, self.humaneval_question_type) != ("claude-3-5-sonnet-20240620", "gpt-4o-mini", "code"):
            raise ValueError("AFlow paper-era model defaults drifted")
        if self.humaneval_operators != ("Custom", "CustomCodeGenerate", "ScEnsemble", "Test"):
            raise ValueError("AFlow HumanEval operator set drifted")
        if self.parent_sampling_explicitly_seeded or self.failure_log_sampling_explicitly_seeded:
            raise ValueError("paper-era AFlow randomness is not explicitly seeded in source")
        if not self.generated_workflow_is_untrusted_code:
            raise ValueError("AFlow generated workflows must be treated as untrusted")


AFLOW_FIDELITY = AFlowFidelity()


__all__ = ["AFLOW_FIDELITY", "AFLOW_PAPER_ERA_COMMIT", "AFLOW_REVIEW_REVISION_COMMIT", "AFlowFidelity"]
