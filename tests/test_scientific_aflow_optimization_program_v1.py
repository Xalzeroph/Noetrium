from __future__ import annotations

import math

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineKind,
    MachineStatus,
    canonical_digest,
)
from research.reproductions.aflow import (
    AFLOW_FIDELITY,
    AFLOW_HUMANEVAL_OPTIMIZATION_PROGRAM,
    AFlowEvaluation,
    AFlowLogSample,
    AFlowMutation,
    AFlowOptimizationBinding,
    AFlowWeightedChoice,
    aflow_convergence,
    aflow_humaneval_host,
    aflow_humaneval_initial_data,
    aflow_humaneval_instance_identity,
    aflow_sampling_probabilities,
)


class _OptimizerModel:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "fake": "aflow-optimizer-model",
            "revision": 1,
        })

    def propose(self, request):
        self.calls += 1
        return AFlowMutation(
            modification=f"mutation-{self.calls}",
            graph_source=(
                "class Workflow:\n"
                f"    round_id = {self.calls + 1}\n"
            ),
            prompt_source=f"PROMPT_{self.calls + 1} = 'paper search candidate'\n",
            receipt={
                "call": self.calls,
                "parent_id": request.parent_candidate["candidate_id"],
                "sampled_log_count": len(request.sampled_logs),
            },
        )


class _Evaluator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "fake": "aflow-workflow-evaluator",
            "revision": 1,
        })

    def evaluate(
        self,
        *,
        candidate_id,
        graph_source,
        prompt_source,
        repetitions,
    ):
        del graph_source, prompt_source
        self.calls.append((candidate_id, repetitions))
        round_number = int(candidate_id.rsplit(":", 1)[1])
        score = 0.40 + (round_number / 100.0)
        return AFlowEvaluation(
            scores=tuple(score for _ in range(repetitions)),
            avg_costs=tuple(0.01 for _ in range(repetitions)),
            total_costs=tuple(0.05 for _ in range(repetitions)),
            logs=tuple(
                {
                    "round": round_number,
                    "case": index,
                    "failure": f"example-{round_number}-{index}",
                }
                for index in range(4)
            ),
            evidence_refs=(
                canonical_digest({
                    "candidate_id": candidate_id,
                    "kind": "evaluation-evidence",
                }),
            ),
            artifact_refs=(
                f"artifact:aflow:{round_number}",
            ),
            receipt={
                "candidate_id": candidate_id,
                "repetitions": repetitions,
            },
        )


class _RandomSource:
    def __init__(self) -> None:
        self.weighted_calls = 0
        self.sample_calls = 0

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "fake": "aflow-random-source",
            "revision": 1,
        })

    def weighted_choice(self, *, candidate_ids, probabilities):
        self.weighted_calls += 1
        assert len(candidate_ids) == len(probabilities)
        assert math.isclose(sum(probabilities), 1.0)
        return AFlowWeightedChoice(
            0,
            receipt={
                "draw": self.weighted_calls,
                "selected_candidate": candidate_ids[0],
            },
        )

    def sample_indices(self, *, population_size, sample_size):
        self.sample_calls += 1
        assert sample_size <= population_size
        return AFlowLogSample(
            tuple(range(sample_size)),
            receipt={
                "draw": self.sample_calls,
                "population_size": population_size,
                "sample_size": sample_size,
            },
        )


def _binding():
    optimizer = _OptimizerModel()
    evaluator = _Evaluator()
    random_source = _RandomSource()
    return (
        AFlowOptimizationBinding(
            optimizer_model=optimizer,
            evaluator=evaluator,
            random_source=random_source,
        ),
        optimizer,
        evaluator,
        random_source,
    )


def test_aflow_is_a_real_optimization_machine_and_runs_round_one_through_21() -> None:
    program = AFLOW_HUMANEVAL_OPTIMIZATION_PROGRAM
    assert program.kind is MachineKind.OPTIMIZATION
    assert program.program_id == "aflow.humaneval.paper-era"

    binding, optimizer, evaluator, random_source = _binding()
    initial_data = aflow_humaneval_initial_data(
        optimization_id="aflow:test:humaneval",
        initial_graph_source="class Workflow:\n    round_id = 1\n",
        initial_prompt_source="PROMPT_1 = 'initial'\n",
    )
    journal = InMemoryMachineJournal()
    host = aflow_humaneval_host(journal)

    execution = host.execute(
        machine_id="optimization:aflow:humaneval:test",
        instance_identity=aflow_humaneval_instance_identity(
            binding=binding,
            initial_data=initial_data,
        ),
        binding=binding,
        initial_data=initial_data,
    )

    assert execution.status is MachineStatus.COMPLETED
    assert execution.previous_value["generated_count"] == 20
    assert execution.previous_value["materialized_round_count"] == 21
    assert execution.previous_value["best_round"] == 21
    assert execution.previous_value["best_candidate_id"] == (
        "aflow:humaneval:round:21"
    )
    assert execution.previous_value["converged"] is False

    assert optimizer.calls == 20
    assert len(evaluator.calls) == 21
    assert all(
        repetitions == AFLOW_FIDELITY.validation_repetitions
        for _, repetitions in evaluator.calls
    )
    assert random_source.weighted_calls == 20
    assert random_source.sample_calls == 20

    assert execution.data["generated_count"] == 20
    assert len(execution.data["candidates"]) == 21
    assert len(execution.data["randomness_receipts"]) == 40
    assert len(
        execution.data["experiences"]["aflow:humaneval:round:1"]["success"]
    ) == 20
    assert len(journal.commits(execution.machine_id)) == 103


def test_aflow_sampling_matches_mixed_uniform_softmax_semantics() -> None:
    probabilities = aflow_sampling_probabilities((0.90, 0.80, 0.50, 0.10))
    assert len(probabilities) == 4
    assert math.isclose(sum(probabilities), 1.0)
    assert probabilities[0] > probabilities[1] > probabilities[2] > probabilities[3]
    assert all(value > 0 for value in probabilities)


def test_aflow_convergence_preserves_paper_zero_width_topk_rule() -> None:
    candidates = {
        f"round-{round_number}": {
            "candidate_id": f"round-{round_number}",
            "round": round_number,
            "scores": (0.5, 0.5, 0.5, 0.5, 0.5),
            "mean_score": 0.5,
            "evaluated": True,
        }
        for round_number in range(1, 7)
    }
    converged, start_index, final_index = aflow_convergence(candidates)
    assert converged is True
    assert (start_index, final_index) == (1, 5)
