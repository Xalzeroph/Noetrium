from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineStatus,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from noetrium_platform.research.execution.machines.api import (
    OptimizationConcern,
    OptimizationProgramBuilder,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgram,
    ResearchProgramHost,
)

from .fidelity import AFLOW_FIDELITY


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _mapping(value: object, field_name: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to an object")
    return decoded


def _finite(value: object, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{field_name} must be finite numeric")
    return float(value)


def _sha(value: str, field_name: str) -> str:
    return require_sha256(value, field_name)


@dataclass(frozen=True, slots=True)
class AFlowMutationRequest:
    parent_candidate: JsonObject
    parent_experience: JsonObject
    sampled_logs: tuple[JsonObject, ...]
    operators: tuple[str, ...]
    question_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.parent_candidate, Mapping):
            raise TypeError("AFlow mutation parent_candidate must be an object")
        if not isinstance(self.parent_experience, Mapping):
            raise TypeError("AFlow mutation parent_experience must be an object")
        if type(self.sampled_logs) is not tuple or any(
            not isinstance(row, Mapping) for row in self.sampled_logs
        ):
            raise TypeError("AFlow sampled logs must be an object tuple")
        if type(self.operators) is not tuple or any(
            type(row) is not str or not row.strip() for row in self.operators
        ):
            raise TypeError("AFlow operators must be a text tuple")
        _text(self.question_type, "AFlow question_type")
        object.__setattr__(
            self,
            "parent_candidate",
            freeze_json(self.parent_candidate),
        )
        object.__setattr__(
            self,
            "parent_experience",
            freeze_json(self.parent_experience),
        )
        object.__setattr__(
            self,
            "sampled_logs",
            tuple(freeze_json(row) for row in self.sampled_logs),
        )


@dataclass(frozen=True, slots=True)
class AFlowMutation:
    modification: str
    graph_source: str
    prompt_source: str
    receipt: JsonValue = None
    mutation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("modification", "graph_source", "prompt_source"):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), f"AFlow mutation {name}"),
            )
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "mutation_digest",
            canonical_digest({
                "modification": self.modification,
                "graph_source": self.graph_source,
                "prompt_source": self.prompt_source,
                "receipt": thaw_json(self.receipt),
            }),
        )


@dataclass(frozen=True, slots=True)
class AFlowEvaluation:
    scores: tuple[float, ...]
    avg_costs: tuple[float, ...] = ()
    total_costs: tuple[float, ...] = ()
    logs: tuple[JsonObject, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    receipt: JsonValue = None
    evaluation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.scores) is not tuple or not self.scores:
            raise ValueError("AFlow evaluation requires scores")
        scores = tuple(_finite(value, "AFlow score") for value in self.scores)
        avg_costs = tuple(_finite(value, "AFlow avg_cost") for value in self.avg_costs)
        total_costs = tuple(
            _finite(value, "AFlow total_cost") for value in self.total_costs
        )
        if avg_costs and len(avg_costs) != len(scores):
            raise ValueError("AFlow avg_cost cardinality must match scores")
        if total_costs and len(total_costs) != len(scores):
            raise ValueError("AFlow total_cost cardinality must match scores")
        if type(self.logs) is not tuple or any(
            not isinstance(row, Mapping) for row in self.logs
        ):
            raise TypeError("AFlow evaluation logs must be an object tuple")
        for field_name in ("evidence_refs", "artifact_refs"):
            values = getattr(self, field_name)
            if type(values) is not tuple or any(
                type(value) is not str or not value.strip() for value in values
            ):
                raise TypeError(f"AFlow {field_name} must be a text tuple")
            if len(values) != len(set(values)):
                raise ValueError(f"AFlow {field_name} must be unique")
        object.__setattr__(self, "scores", scores)
        object.__setattr__(self, "avg_costs", avg_costs)
        object.__setattr__(self, "total_costs", total_costs)
        object.__setattr__(
            self,
            "logs",
            tuple(freeze_json(row) for row in self.logs),
        )
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "evaluation_digest",
            canonical_digest({
                "scores": scores,
                "avg_costs": avg_costs,
                "total_costs": total_costs,
                "logs": tuple(thaw_json(row) for row in self.logs),
                "evidence_refs": self.evidence_refs,
                "artifact_refs": self.artifact_refs,
                "receipt": thaw_json(self.receipt),
            }),
        )

    @property
    def mean_score(self) -> float:
        return sum(self.scores) / len(self.scores)

    @property
    def score_std(self) -> float:
        mean = self.mean_score
        return math.sqrt(
            sum((value - mean) ** 2 for value in self.scores)
            / len(self.scores)
        )


@dataclass(frozen=True, slots=True)
class AFlowWeightedChoice:
    index: int
    receipt: JsonValue = None

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 0:
            raise ValueError("AFlow weighted choice index must be non-negative")
        object.__setattr__(self, "receipt", freeze_json(self.receipt))


@dataclass(frozen=True, slots=True)
class AFlowLogSample:
    indices: tuple[int, ...]
    receipt: JsonValue = None

    def __post_init__(self) -> None:
        if type(self.indices) is not tuple or any(
            type(value) is not int or value < 0 for value in self.indices
        ):
            raise TypeError("AFlow log sample indices must be non-negative ints")
        if len(self.indices) != len(set(self.indices)):
            raise ValueError("AFlow log sample indices must be unique")
        object.__setattr__(self, "receipt", freeze_json(self.receipt))


@runtime_checkable
class AFlowOptimizerModelPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def propose(self, request: AFlowMutationRequest) -> AFlowMutation: ...


@runtime_checkable
class AFlowWorkflowEvaluatorPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def evaluate(
        self,
        *,
        candidate_id: str,
        graph_source: str,
        prompt_source: str,
        repetitions: int,
    ) -> AFlowEvaluation: ...


@runtime_checkable
class AFlowRandomSourcePort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def weighted_choice(
        self,
        *,
        candidate_ids: tuple[str, ...],
        probabilities: tuple[float, ...],
    ) -> AFlowWeightedChoice: ...

    def sample_indices(
        self,
        *,
        population_size: int,
        sample_size: int,
    ) -> AFlowLogSample: ...


@dataclass(frozen=True, slots=True)
class AFlowOptimizationBinding:
    optimizer_model: AFlowOptimizerModelPort
    evaluator: AFlowWorkflowEvaluatorPort
    random_source: AFlowRandomSourcePort
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.optimizer_model, AFlowOptimizerModelPort):
            raise TypeError("AFlow binding requires optimizer model port")
        if not isinstance(self.evaluator, AFlowWorkflowEvaluatorPort):
            raise TypeError("AFlow binding requires workflow evaluator port")
        if not isinstance(self.random_source, AFlowRandomSourcePort):
            raise TypeError("AFlow binding requires random source port")
        identities = {
            "optimizer_model": _sha(
                self.optimizer_model.identity_digest,
                "AFlow optimizer model identity_digest",
            ),
            "evaluator": _sha(
                self.evaluator.identity_digest,
                "AFlow evaluator identity_digest",
            ),
            "random_source": _sha(
                self.random_source.identity_digest,
                "AFlow random source identity_digest",
            ),
        }
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "fidelity_digest": AFLOW_FIDELITY.fidelity_digest,
                "bindings": identities,
            }),
        )


def aflow_sampling_probabilities(scores: Sequence[float]) -> tuple[float, ...]:
    if not scores:
        raise ValueError("AFlow sampling requires scores")
    scaled = tuple(
        _finite(value, "AFlow parent score") * AFLOW_FIDELITY.score_scale
        for value in scores
    )
    maximum = max(scaled)
    weights = tuple(
        math.exp(AFLOW_FIDELITY.softmax_alpha * (value - maximum))
        for value in scaled
    )
    total = sum(weights)
    if total <= 0 or not math.isfinite(total):
        raise ValueError("AFlow softmax weights cannot be normalized")
    score_prob = tuple(value / total for value in weights)
    uniform = 1.0 / len(scaled)
    mixed = tuple(
        AFLOW_FIDELITY.uniform_mix_weight * uniform
        + AFLOW_FIDELITY.score_softmax_weight * value
        for value in score_prob
    )
    mixed_total = sum(mixed)
    return tuple(value / mixed_total for value in mixed)


def _round_number(candidate: Mapping[str, JsonValue]) -> int:
    value = candidate.get("round")
    if type(value) is not int or value < 1:
        raise ValueError("AFlow candidate round is invalid")
    return value


def _mean_score(candidate: Mapping[str, JsonValue]) -> float:
    return _finite(candidate.get("mean_score"), "AFlow candidate mean_score")


def aflow_parent_pool(
    candidates: Mapping[str, JsonValue],
) -> tuple[JsonObject, ...]:
    rows: list[JsonObject] = []
    for value in candidates.values():
        if not isinstance(value, Mapping) or value.get("evaluated") is not True:
            continue
        rows.append(dict(thaw_json(value)))
    if not rows:
        raise ValueError("AFlow parent selection requires evaluated workflows")
    rows.sort(key=lambda row: (-_mean_score(row), _round_number(row)))
    initial = next(
        (row for row in rows if _round_number(row) == AFLOW_FIDELITY.initial_round),
        None,
    )
    if initial is None:
        raise ValueError("AFlow parent pool lost initial round")
    selected = [initial]
    selected_rounds = {AFLOW_FIDELITY.initial_round}
    for row in rows:
        round_number = _round_number(row)
        if round_number in selected_rounds:
            continue
        selected.append(row)
        selected_rounds.add(round_number)
        if len(selected) >= AFLOW_FIDELITY.parent_pool_size:
            break
    return tuple(freeze_json(row) for row in selected)


def aflow_convergence(
    candidates: Mapping[str, JsonValue],
) -> tuple[bool, int | None, int | None]:
    rows: list[tuple[int, float, float]] = []
    for value in candidates.values():
        if not isinstance(value, Mapping) or value.get("evaluated") is not True:
            continue
        scores_value = value.get("scores")
        if not isinstance(scores_value, (tuple, list)) or not scores_value:
            raise TypeError("AFlow candidate scores must be a sequence")
        scores = tuple(_finite(row, "AFlow candidate score") for row in scores_value)
        mean = sum(scores) / len(scores)
        std = math.sqrt(sum((row - mean) ** 2 for row in scores) / len(scores))
        rows.append((_round_number(value), mean, std))
    rows.sort(key=lambda row: row[0])
    top_k = AFLOW_FIDELITY.convergence_top_k
    if len(rows) < top_k + 1:
        return False, None, None

    previous_y: float | None = None
    previous_sigma: float | None = None
    convergence_count = 0
    for index in range(len(rows)):
        prefix = rows[: index + 1]
        ranked = sorted(prefix, key=lambda row: row[1], reverse=True)[:top_k]
        y_current = sum(row[1] for row in ranked) / len(ranked)
        sigma_current = math.sqrt(
            sum(row[2] ** 2 for row in ranked) / (top_k**2)
        )
        if previous_y is not None and previous_sigma is not None:
            delta = y_current - previous_y
            sigma_delta = math.sqrt(
                sigma_current**2 + previous_sigma**2
            )
            if abs(delta) <= AFLOW_FIDELITY.convergence_z * sigma_delta:
                convergence_count += 1
                if (
                    convergence_count
                    >= AFLOW_FIDELITY.convergence_consecutive_rounds
                ):
                    return (
                        True,
                        index
                        - AFLOW_FIDELITY.convergence_consecutive_rounds
                        + 1,
                        index,
                    )
            else:
                convergence_count = 0
        previous_y = y_current
        previous_sigma = sigma_current
    return False, None, None


def aflow_humaneval_initial_data(
    *,
    optimization_id: str,
    initial_graph_source: str,
    initial_prompt_source: str,
) -> JsonObject:
    candidate_id = "aflow:humaneval:round:1"
    candidate = {
        "candidate_id": candidate_id,
        "round": 1,
        "parent_id": None,
        "modification": "initial_workflow",
        "graph_source": _text(initial_graph_source, "AFlow initial graph source"),
        "prompt_source": _text(initial_prompt_source, "AFlow initial prompt source"),
        "mutation_digest": None,
        "scores": (),
        "mean_score": None,
        "score_std": None,
        "logs": (),
        "evaluation_digest": None,
        "evaluated": False,
    }
    return {
        "optimization_id": _text(optimization_id, "AFlow optimization_id"),
        "fidelity_digest": AFLOW_FIDELITY.fidelity_digest,
        "dataset": "HumanEval",
        "question_type": AFLOW_FIDELITY.humaneval_question_type,
        "operators": AFLOW_FIDELITY.humaneval_operators,
        "generated_count": 0,
        "candidates": {candidate_id: candidate},
        "selected_parent_id": None,
        "selected_log_indices": (),
        "pending_candidate": None,
        "experiences": {},
        "randomness_receipts": (),
        "converged": False,
        "convergence_start_index": None,
        "convergence_final_index": None,
    }


def _evaluate_candidate(
    binding: AFlowOptimizationBinding,
    candidate: Mapping[str, JsonValue],
) -> tuple[JsonObject, AFlowEvaluation]:
    candidate_id = _text(candidate.get("candidate_id"), "AFlow candidate_id")
    evaluation = binding.evaluator.evaluate(
        candidate_id=candidate_id,
        graph_source=_text(candidate.get("graph_source"), "AFlow graph_source"),
        prompt_source=_text(candidate.get("prompt_source"), "AFlow prompt_source"),
        repetitions=AFLOW_FIDELITY.validation_repetitions,
    )
    if not isinstance(evaluation, AFlowEvaluation):
        raise TypeError("AFlow evaluator must return AFlowEvaluation")
    if len(evaluation.scores) != AFLOW_FIDELITY.validation_repetitions:
        raise ValueError("AFlow evaluator repetition cardinality drifted")
    row = dict(thaw_json(candidate))
    row.update({
        "scores": evaluation.scores,
        "mean_score": evaluation.mean_score,
        "score_std": evaluation.score_std,
        "logs": tuple(thaw_json(log) for log in evaluation.logs),
        "evaluation_digest": evaluation.evaluation_digest,
        "evaluated": True,
    })
    return freeze_json(row), evaluation


def _initial_evaluate(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, AFlowOptimizationBinding):
        raise TypeError("AFlow host requires AFlowOptimizationBinding")
    data = _mapping(request.data, "AFlow state")
    if data.get("fidelity_digest") != AFLOW_FIDELITY.fidelity_digest:
        raise ValueError("AFlow fidelity identity drifted")
    candidates = _mapping(data.get("candidates", {}), "AFlow candidates")
    candidate_id = "aflow:humaneval:round:1"
    current = candidates.get(candidate_id)
    if not isinstance(current, Mapping):
        raise ValueError("AFlow initial workflow is missing")
    if current.get("evaluated") is True:
        return ProgramNodeResult(
            value={"candidate_id": candidate_id, "replayed": True},
            next_node="select_parent",
        )
    evaluated, result = _evaluate_candidate(binding, current)
    candidates[candidate_id] = evaluated
    return ProgramNodeResult(
        value={
            "candidate_id": candidate_id,
            "mean_score": evaluated["mean_score"],
            "evaluation_digest": result.evaluation_digest,
        },
        state_update={"candidates": candidates},
        next_node="select_parent",
        events=({
            "type": "aflow_initial_workflow_evaluated",
            "candidate_id": candidate_id,
            "mean_score": evaluated["mean_score"],
            "evaluation_digest": result.evaluation_digest,
        },),
        evidence_refs=result.evidence_refs,
        artifact_refs=result.artifact_refs,
    )


def _select_parent(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, AFlowOptimizationBinding):
        raise TypeError("AFlow host requires AFlowOptimizationBinding")
    data = _mapping(request.data, "AFlow state")
    candidates = _mapping(data.get("candidates", {}), "AFlow candidates")
    pool = aflow_parent_pool(candidates)
    candidate_ids = tuple(
        _text(row["candidate_id"], "AFlow parent candidate_id")
        for row in pool
    )
    probabilities = aflow_sampling_probabilities(
        tuple(_mean_score(row) for row in pool)
    )
    choice = binding.random_source.weighted_choice(
        candidate_ids=candidate_ids,
        probabilities=probabilities,
    )
    if not isinstance(choice, AFlowWeightedChoice):
        raise TypeError("AFlow random source must return AFlowWeightedChoice")
    if choice.index >= len(pool):
        raise ValueError("AFlow random source selected outside parent pool")
    parent = pool[choice.index]
    logs_value = parent.get("logs", ())
    if not isinstance(logs_value, (tuple, list)):
        raise TypeError("AFlow parent logs must be a sequence")
    log_count = min(AFLOW_FIDELITY.sampled_failure_log_count, len(logs_value))
    sample = binding.random_source.sample_indices(
        population_size=len(logs_value),
        sample_size=log_count,
    )
    if not isinstance(sample, AFlowLogSample):
        raise TypeError("AFlow random source must return AFlowLogSample")
    if len(sample.indices) != log_count or any(
        index >= len(logs_value) for index in sample.indices
    ):
        raise ValueError("AFlow log sample does not match requested population")

    receipts_value = data.get("randomness_receipts", ())
    if not isinstance(receipts_value, (tuple, list)):
        raise TypeError("AFlow randomness receipts must be a sequence")
    receipts = tuple(receipts_value) + (
        {
            "kind": "parent_weighted_choice",
            "candidate_ids": candidate_ids,
            "probabilities": probabilities,
            "selected_index": choice.index,
            "receipt": thaw_json(choice.receipt),
        },
        {
            "kind": "parent_log_sample",
            "population_size": len(logs_value),
            "sample_size": log_count,
            "indices": sample.indices,
            "receipt": thaw_json(sample.receipt),
        },
    )
    return ProgramNodeResult(
        value={
            "parent_id": parent["candidate_id"],
            "probabilities": probabilities,
        },
        state_update={
            "selected_parent_id": parent["candidate_id"],
            "selected_log_indices": sample.indices,
            "randomness_receipts": receipts,
        },
        next_node="propose",
        events=({
            "type": "aflow_parent_selected",
            "parent_id": parent["candidate_id"],
            "candidate_ids": candidate_ids,
            "probabilities": probabilities,
            "selected_index": choice.index,
        },),
    )


def _propose(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, AFlowOptimizationBinding):
        raise TypeError("AFlow host requires AFlowOptimizationBinding")
    data = _mapping(request.data, "AFlow state")
    candidates = _mapping(data.get("candidates", {}), "AFlow candidates")
    parent_id = _text(
        data.get("selected_parent_id"),
        "AFlow selected_parent_id",
    )
    parent = candidates.get(parent_id)
    if not isinstance(parent, Mapping):
        raise KeyError(parent_id)
    experiences = _mapping(data.get("experiences", {}), "AFlow experiences")
    experience = experiences.get(parent_id, {
        "score": parent.get("mean_score"),
        "success": (),
        "failure": (),
    })
    if not isinstance(experience, Mapping):
        raise TypeError("AFlow parent experience must be an object")

    logs_value = parent.get("logs", ())
    if not isinstance(logs_value, (tuple, list)):
        raise TypeError("AFlow parent logs must be a sequence")
    indices_value = data.get("selected_log_indices", ())
    if not isinstance(indices_value, (tuple, list)):
        raise TypeError("AFlow selected log indices must be a sequence")
    sampled_logs = tuple(
        freeze_json(logs_value[int(index)]) for index in indices_value
    )

    mutation = binding.optimizer_model.propose(
        AFlowMutationRequest(
            parent_candidate=parent,
            parent_experience=experience,
            sampled_logs=sampled_logs,
            operators=AFLOW_FIDELITY.humaneval_operators,
            question_type=AFLOW_FIDELITY.humaneval_question_type,
        )
    )
    if not isinstance(mutation, AFlowMutation):
        raise TypeError("AFlow optimizer model must return AFlowMutation")

    generated_count = data.get("generated_count", 0)
    if type(generated_count) is not int or generated_count < 0:
        raise ValueError("AFlow generated_count is invalid")
    round_number = AFLOW_FIDELITY.initial_round + generated_count + 1
    candidate_id = f"aflow:humaneval:round:{round_number}"
    pending = {
        "candidate_id": candidate_id,
        "round": round_number,
        "parent_id": parent_id,
        "modification": mutation.modification,
        "graph_source": mutation.graph_source,
        "prompt_source": mutation.prompt_source,
        "mutation_digest": mutation.mutation_digest,
        "scores": (),
        "mean_score": None,
        "score_std": None,
        "logs": (),
        "evaluation_digest": None,
        "evaluated": False,
    }
    return ProgramNodeResult(
        value={
            "candidate_id": candidate_id,
            "round": round_number,
            "mutation_digest": mutation.mutation_digest,
        },
        state_update={"pending_candidate": pending},
        next_node="evaluate_candidate",
        events=({
            "type": "aflow_workflow_mutated",
            "candidate_id": candidate_id,
            "round": round_number,
            "parent_id": parent_id,
            "mutation_digest": mutation.mutation_digest,
        },),
    )


def _evaluate_pending(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, AFlowOptimizationBinding):
        raise TypeError("AFlow host requires AFlowOptimizationBinding")
    data = _mapping(request.data, "AFlow state")
    pending = data.get("pending_candidate")
    if not isinstance(pending, Mapping):
        raise ValueError("AFlow pending candidate is missing")
    evaluated, result = _evaluate_candidate(binding, pending)
    return ProgramNodeResult(
        value={
            "candidate_id": evaluated["candidate_id"],
            "mean_score": evaluated["mean_score"],
            "evaluation_digest": result.evaluation_digest,
        },
        state_update={"pending_candidate": evaluated},
        next_node="record_generation",
        events=({
            "type": "aflow_workflow_evaluated",
            "candidate_id": evaluated["candidate_id"],
            "round": evaluated["round"],
            "mean_score": evaluated["mean_score"],
            "evaluation_digest": result.evaluation_digest,
        },),
        evidence_refs=result.evidence_refs,
        artifact_refs=result.artifact_refs,
    )


def _record_generation(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, AFlowOptimizationBinding):
        raise TypeError("AFlow host requires AFlowOptimizationBinding")
    data = _mapping(request.data, "AFlow state")
    pending = data.get("pending_candidate")
    if not isinstance(pending, Mapping) or pending.get("evaluated") is not True:
        raise ValueError("AFlow can record only an evaluated pending workflow")
    parent_id = _text(pending.get("parent_id"), "AFlow parent_id")
    candidates = _mapping(data.get("candidates", {}), "AFlow candidates")
    parent = candidates.get(parent_id)
    if not isinstance(parent, Mapping):
        raise KeyError(parent_id)
    candidate_id = _text(pending.get("candidate_id"), "AFlow candidate_id")
    existing = candidates.get(candidate_id)
    if existing is not None and canonical_digest(existing) != canonical_digest(pending):
        raise ValueError("AFlow candidate identity was reused with drift")
    candidates[candidate_id] = freeze_json(pending)

    before = _mean_score(parent)
    after = _mean_score(pending)
    success = after > before
    experiences = _mapping(data.get("experiences", {}), "AFlow experiences")
    current = experiences.get(parent_id, {
        "score": before,
        "success": (),
        "failure": (),
    })
    if not isinstance(current, Mapping):
        raise TypeError("AFlow parent experience must be an object")
    row = {
        "round": _round_number(pending),
        "modification": pending.get("modification"),
        "score": after,
    }
    successes = tuple(current.get("success", ()))
    failures = tuple(current.get("failure", ()))
    if success:
        successes = (*successes, row)
    else:
        failures = (*failures, row)
    experiences[parent_id] = {
        "score": before,
        "success": successes,
        "failure": failures,
    }

    generated_count = data.get("generated_count", 0)
    if type(generated_count) is not int or generated_count < 0:
        raise ValueError("AFlow generated_count is invalid")
    generated_count += 1
    return ProgramNodeResult(
        value={
            "candidate_id": candidate_id,
            "parent_id": parent_id,
            "before": before,
            "after": after,
            "succeed": success,
        },
        state_update={
            "candidates": candidates,
            "experiences": experiences,
            "generated_count": generated_count,
            "pending_candidate": None,
        },
        next_node="check_convergence",
        events=({
            "type": "aflow_experience_recorded",
            "candidate_id": candidate_id,
            "parent_id": parent_id,
            "before": before,
            "after": after,
            "succeed": success,
            "generated_count": generated_count,
        },),
    )


def _check_convergence(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, AFlowOptimizationBinding):
        raise TypeError("AFlow host requires AFlowOptimizationBinding")
    data = _mapping(request.data, "AFlow state")
    candidates = _mapping(data.get("candidates", {}), "AFlow candidates")
    converged, start_index, final_index = aflow_convergence(candidates)
    generated_count = data.get("generated_count", 0)
    if type(generated_count) is not int or generated_count < 0:
        raise ValueError("AFlow generated_count is invalid")
    budget_exhausted = (
        generated_count >= AFLOW_FIDELITY.optimization_iterations
    )
    should_stop = (
        budget_exhausted
        or (
            AFLOW_FIDELITY.convergence_enabled_by_default
            and converged
        )
    )
    return ProgramNodeResult(
        value={
            "converged": converged,
            "convergence_start_index": start_index,
            "convergence_final_index": final_index,
            "budget_exhausted": budget_exhausted,
        },
        state_update={
            "converged": converged,
            "convergence_start_index": start_index,
            "convergence_final_index": final_index,
        },
        next_node="finalize" if should_stop else "select_parent",
        events=({
            "type": "aflow_stop_condition_checked",
            "generated_count": generated_count,
            "converged": converged,
            "budget_exhausted": budget_exhausted,
        },),
    )


def _finalize(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, AFlowOptimizationBinding):
        raise TypeError("AFlow host requires AFlowOptimizationBinding")
    data = _mapping(request.data, "AFlow state")
    candidates = _mapping(data.get("candidates", {}), "AFlow candidates")
    evaluated = [
        dict(thaw_json(row))
        for row in candidates.values()
        if isinstance(row, Mapping) and row.get("evaluated") is True
    ]
    if not evaluated:
        raise ValueError("AFlow finalization requires evaluated workflows")
    evaluated.sort(key=lambda row: (-_mean_score(row), _round_number(row)))
    best = evaluated[0]
    result_digest = canonical_digest({
        "optimization_id": data.get("optimization_id"),
        "fidelity_digest": AFLOW_FIDELITY.fidelity_digest,
        "binding_digest": binding.binding_digest,
        "generated_count": data.get("generated_count"),
        "best_candidate_id": best.get("candidate_id"),
        "best_mean_score": best.get("mean_score"),
        "candidate_digests": tuple(
            canonical_digest(row)
            for row in sorted(evaluated, key=_round_number)
        ),
    })
    return ProgramNodeResult(
        value={
            "best_candidate_id": best["candidate_id"],
            "best_round": best["round"],
            "best_mean_score": best["mean_score"],
            "generated_count": data.get("generated_count"),
            "materialized_round_count": len(evaluated),
            "converged": data.get("converged"),
            "result_digest": result_digest,
        },
        state_update={"result_digest": result_digest},
        status=MachineStatus.COMPLETED,
        events=({
            "type": "aflow_optimization_finalized",
            "best_candidate_id": best["candidate_id"],
            "best_round": best["round"],
            "best_mean_score": best["mean_score"],
            "result_digest": result_digest,
        },),
    )


def build_aflow_humaneval_optimization_program() -> ResearchProgram:
    builder = OptimizationProgramBuilder.create(
        program_id="aflow.humaneval.paper-era",
        version="1",
        state_schema="aflow.humaneval.optimization-state.v1",
        entrypoint="evaluate_initial",
    )
    builder.semantic(
        "evaluate_initial",
        OptimizationConcern.EVALUATION,
        "aflow.initial.evaluate",
        next_node="select_parent",
    )
    builder.semantic(
        "select_parent",
        OptimizationConcern.SELECTION,
        "aflow.parent.select",
        next_node="propose",
    )
    builder.semantic(
        "propose",
        OptimizationConcern.MUTATION,
        "aflow.workflow.mutate",
        next_node="evaluate_candidate",
    )
    builder.semantic(
        "evaluate_candidate",
        OptimizationConcern.EVALUATION,
        "aflow.workflow.evaluate",
        next_node="record_generation",
    )
    builder.semantic(
        "record_generation",
        OptimizationConcern.GENERATION,
        "aflow.experience.record",
        next_node="check_convergence",
    )
    builder.semantic(
        "check_convergence",
        OptimizationConcern.TERMINATION,
        "aflow.convergence.check",
        next_node="select_parent",
    )
    builder.semantic(
        "finalize",
        OptimizationConcern.TERMINATION,
        "aflow.finalize",
    )
    return builder.build()


AFLOW_HUMANEVAL_OPTIMIZATION_PROGRAM = (
    build_aflow_humaneval_optimization_program()
)


def _operation_digest(operation: str) -> str:
    return canonical_digest({
        "paper": "aflow",
        "source_commit": AFLOW_FIDELITY.audited_commit,
        "operation": operation,
        "implementation_revision": 1,
    })


def aflow_humaneval_operations() -> tuple[ResearchHostOperation, ...]:
    rows = (
        ("aflow.initial.evaluate", _initial_evaluate),
        ("aflow.parent.select", _select_parent),
        ("aflow.workflow.mutate", _propose),
        ("aflow.workflow.evaluate", _evaluate_pending),
        ("aflow.experience.record", _record_generation),
        ("aflow.convergence.check", _check_convergence),
        ("aflow.finalize", _finalize),
    )
    return tuple(
        ResearchHostOperation(
            operation,
            handler,
            _operation_digest(operation),
        )
        for operation, handler in rows
    )


def aflow_humaneval_host(
    journal: MachineJournalPort,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="aflow.humaneval.optimization",
        program=AFLOW_HUMANEVAL_OPTIMIZATION_PROGRAM,
        operations=aflow_humaneval_operations(),
        journal=journal,
        max_steps=256,
        dependency_identity={
            "paper": "AFlow",
            "source_commit": AFLOW_FIDELITY.audited_commit,
            "fidelity_digest": AFLOW_FIDELITY.fidelity_digest,
            "dataset": "HumanEval",
        },
    )


def aflow_humaneval_instance_identity(
    *,
    binding: AFlowOptimizationBinding,
    initial_data: JsonObject,
) -> JsonObject:
    if not isinstance(binding, AFlowOptimizationBinding):
        raise TypeError("AFlow instance identity requires binding")
    return {
        "program_digest": AFLOW_HUMANEVAL_OPTIMIZATION_PROGRAM.program_digest,
        "fidelity_digest": AFLOW_FIDELITY.fidelity_digest,
        "binding_digest": binding.binding_digest,
        "initial_data_digest": canonical_digest(initial_data),
    }


__all__ = [
    "AFLOW_HUMANEVAL_OPTIMIZATION_PROGRAM",
    "AFlowEvaluation",
    "AFlowLogSample",
    "AFlowMutation",
    "AFlowMutationRequest",
    "AFlowOptimizationBinding",
    "AFlowOptimizerModelPort",
    "AFlowRandomSourcePort",
    "AFlowWeightedChoice",
    "AFlowWorkflowEvaluatorPort",
    "aflow_convergence",
    "aflow_humaneval_host",
    "aflow_humaneval_initial_data",
    "aflow_humaneval_instance_identity",
    "aflow_humaneval_operations",
    "aflow_parent_pool",
    "aflow_sampling_probabilities",
    "build_aflow_humaneval_optimization_program",
]
