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

from .fidelity import AGENTSQUARE_FIDELITY


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"AgentSquare {field} must be non-empty text")
    return value.strip()


def _score(value: object, field: str = "score") -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"AgentSquare {field} must be finite numeric")
    return float(value)


def _mapping(value: object, field: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"AgentSquare {field} must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"AgentSquare {field} must decode to an object")
    return decoded


def _agent(value: object) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError("AgentSquare agent must be an object")
    row = {
        module_type: _text(value.get(module_type), f"agent {module_type}")
        for module_type in AGENTSQUARE_FIDELITY.module_types
    }
    return freeze_json(row)


def _agents(value: object) -> tuple[JsonObject, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError("AgentSquare candidate agents must be a sequence")
    rows = tuple(_agent(row) for row in value)
    if not rows:
        raise ValueError("AgentSquare candidate agents cannot be empty")
    return rows


def _archives(value: object) -> dict[str, JsonValue]:
    rows = _mapping(value, "module archives")
    if set(rows) != set(AGENTSQUARE_FIDELITY.module_types):
        raise ValueError("AgentSquare module archive keys drifted")
    return rows


@dataclass(frozen=True, slots=True)
class AgentSquareEvolutionProposal:
    module_proposals: JsonObject
    candidate_agents: tuple[JsonObject, ...]
    receipt: JsonValue = None

    def __post_init__(self) -> None:
        if not isinstance(self.module_proposals, Mapping):
            raise TypeError("AgentSquare module_proposals must be an object")
        proposals = dict(thaw_json(self.module_proposals))
        if set(proposals) != set(AGENTSQUARE_FIDELITY.module_types):
            raise ValueError("AgentSquare evolution must propose all four module types")
        normalized: dict[str, JsonValue] = {}
        for module_type, raw in proposals.items():
            if not isinstance(raw, Mapping):
                raise TypeError("AgentSquare module proposal must be an object")
            normalized[module_type] = freeze_json({
                "name": _text(raw.get("name"), f"{module_type} module name"),
                "thought": _text(raw.get("thought"), f"{module_type} module thought"),
                "code": _text(raw.get("code"), f"{module_type} module code"),
                "module_type": module_type,
            })
        candidates = _agents(self.candidate_agents)
        object.__setattr__(self, "module_proposals", freeze_json(normalized))
        object.__setattr__(self, "candidate_agents", candidates)
        object.__setattr__(self, "receipt", freeze_json(self.receipt))


@dataclass(frozen=True, slots=True)
class AgentSquareEvaluation:
    agent: JsonObject
    performance: float
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    receipt: JsonValue = None
    evaluation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        agent = _agent(self.agent)
        performance = _score(self.performance, "performance")
        for field_name in ("evidence_refs", "artifact_refs"):
            values = getattr(self, field_name)
            if type(values) is not tuple or any(
                type(row) is not str or not row.strip() for row in values
            ):
                raise TypeError(f"AgentSquare {field_name} must be a text tuple")
            if len(values) != len(set(values)):
                raise ValueError(f"AgentSquare {field_name} must be unique")
        object.__setattr__(self, "agent", agent)
        object.__setattr__(self, "performance", performance)
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "evaluation_digest",
            canonical_digest({
                "agent": thaw_json(agent),
                "performance": performance,
                "evidence_refs": self.evidence_refs,
                "artifact_refs": self.artifact_refs,
                "receipt": thaw_json(self.receipt),
            }),
        )


@dataclass(frozen=True, slots=True)
class AgentSquareModuleEvaluation:
    module_type: str
    module_name: str
    performance: float
    evidence_refs: tuple[str, ...] = ()
    receipt: JsonValue = None

    def __post_init__(self) -> None:
        if self.module_type not in AGENTSQUARE_FIDELITY.module_types:
            raise ValueError("AgentSquare module evaluation type drifted")
        object.__setattr__(self, "module_name", _text(self.module_name, "module_name"))
        object.__setattr__(
            self,
            "performance",
            _score(self.performance, "module performance"),
        )
        if type(self.evidence_refs) is not tuple or any(
            type(row) is not str or not row.strip() for row in self.evidence_refs
        ):
            raise TypeError("AgentSquare module evidence_refs must be a text tuple")
        object.__setattr__(self, "receipt", freeze_json(self.receipt))


@runtime_checkable
class AgentSquareSearchModelPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def evolve(
        self,
        *,
        current_agent: JsonObject,
        module_archives: JsonObject,
    ) -> AgentSquareEvolutionProposal: ...

    def recombine(
        self,
        *,
        current_agent: JsonObject,
        module_archives: JsonObject,
        tested_cases: tuple[JsonObject, ...],
    ) -> tuple[JsonObject, ...]: ...

    def predict(
        self,
        *,
        module_archives: JsonObject,
        tested_cases: tuple[JsonObject, ...],
        candidates: tuple[JsonObject, ...],
    ) -> tuple[float, ...]: ...


@runtime_checkable
class AgentSquareEvaluatorPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def evaluate_module(
        self,
        *,
        module_type: str,
        module: JsonObject,
        episodes: int,
    ) -> AgentSquareModuleEvaluation: ...

    def evaluate_agent(
        self,
        *,
        agent: JsonObject,
        episodes: int,
    ) -> AgentSquareEvaluation: ...


@dataclass(frozen=True, slots=True)
class AgentSquareOptimizationBinding:
    search_model: AgentSquareSearchModelPort
    evaluator: AgentSquareEvaluatorPort
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.search_model, AgentSquareSearchModelPort):
            raise TypeError("AgentSquare binding requires search model port")
        if not isinstance(self.evaluator, AgentSquareEvaluatorPort):
            raise TypeError("AgentSquare binding requires evaluator port")
        model_digest = require_sha256(
            self.search_model.identity_digest,
            "AgentSquare search model identity_digest",
        )
        evaluator_digest = require_sha256(
            self.evaluator.identity_digest,
            "AgentSquare evaluator identity_digest",
        )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "fidelity_digest": AGENTSQUARE_FIDELITY.fidelity_digest,
                "search_model": model_digest,
                "evaluator": evaluator_digest,
            }),
        )


def agentsquare_alfworld_initial_data(
    *,
    optimization_id: str,
    module_archives: JsonObject,
) -> JsonObject:
    archives = _archives(module_archives)
    initial = freeze_json(dict(zip(
        AGENTSQUARE_FIDELITY.module_types,
        AGENTSQUARE_FIDELITY.released_initial_agent,
        strict=True,
    )))
    initial_case = freeze_json({
        **thaw_json(initial),
        "performance": AGENTSQUARE_FIDELITY.released_initial_performance,
    })
    return {
        "optimization_id": _text(optimization_id, "optimization_id"),
        "fidelity_digest": AGENTSQUARE_FIDELITY.fidelity_digest,
        "iteration": 0,
        "module_archives": freeze_json(archives),
        "current_agent": initial,
        "current_performance": AGENTSQUARE_FIDELITY.released_initial_performance,
        "tested_cases": (initial_case,),
        "pending_modules": {},
        "pending_evolution_agents": (),
        "pending_recombination_agents": (),
        "pending_predictions": (),
        "best_history": ({
            "iteration": 0,
            "agent": initial,
            "performance": AGENTSQUARE_FIDELITY.released_initial_performance,
        },),
        "evaluation_count": 0,
        "model_receipts": (),
    }


def _require_binding(binding: object) -> AgentSquareOptimizationBinding:
    if not isinstance(binding, AgentSquareOptimizationBinding):
        raise TypeError("AgentSquare host requires AgentSquareOptimizationBinding")
    return binding


def _state(request: ProgramNodeRequest) -> dict[str, JsonValue]:
    data = _mapping(request.data, "state")
    if data.get("fidelity_digest") != AGENTSQUARE_FIDELITY.fidelity_digest:
        raise ValueError("AgentSquare fidelity identity drifted")
    return data


def _evolve(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
    bound = _require_binding(binding)
    data = _state(request)
    proposal = bound.search_model.evolve(
        current_agent=_agent(data.get("current_agent")),
        module_archives=freeze_json(_archives(data.get("module_archives"))),
    )
    if not isinstance(proposal, AgentSquareEvolutionProposal):
        raise TypeError("AgentSquare evolve must return AgentSquareEvolutionProposal")
    receipts = tuple(data.get("model_receipts", ())) + ({
        "phase": "evolution",
        "receipt": thaw_json(proposal.receipt),
    },)
    return ProgramNodeResult(
        value={"candidate_count": len(proposal.candidate_agents)},
        state_update={
            "pending_modules": proposal.module_proposals,
            "pending_evolution_agents": proposal.candidate_agents,
            "model_receipts": receipts,
        },
        next_node="validate_modules",
        events=({
            "type": "agentsquare_module_evolution_proposed",
            "iteration": data.get("iteration"),
            "candidate_count": len(proposal.candidate_agents),
        },),
    )


def _validate_modules(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    bound = _require_binding(binding)
    data = _state(request)
    proposals = _mapping(data.get("pending_modules", {}), "pending modules")
    archives = _archives(data.get("module_archives"))
    rejected: set[str] = set()
    evidence: list[str] = []
    module_receipts: list[JsonValue] = []
    for module_type in AGENTSQUARE_FIDELITY.module_types:
        # The released ALFWorld search explicitly skips standalone tool-use
        # module validation; preserve that executable semantics.
        if module_type == "tooluse":
            continue
        raw = proposals.get(module_type)
        if not isinstance(raw, Mapping):
            raise ValueError(f"AgentSquare missing {module_type} proposal")
        result = bound.evaluator.evaluate_module(
            module_type=module_type,
            module=freeze_json(raw),
            episodes=AGENTSQUARE_FIDELITY.released_candidate_eval_episodes,
        )
        if not isinstance(result, AgentSquareModuleEvaluation):
            raise TypeError("AgentSquare evaluator returned invalid module result")
        evidence.extend(result.evidence_refs)
        module_receipts.append({
            "module_type": module_type,
            "module_name": result.module_name,
            "performance": result.performance,
            "receipt": thaw_json(result.receipt),
        })
        if result.performance > 0:
            rows = list(archives[module_type])
            accepted = dict(thaw_json(raw))
            accepted["performance"] = result.performance
            rows.append(freeze_json(accepted))
            archives[module_type] = tuple(rows)
        else:
            rejected.add(result.module_name)

    candidates = tuple(
        row
        for row in _agents(data.get("pending_evolution_agents", ()))
        if not any(value in rejected for value in row.values())
        and row.get("tooluse") == "None"
    )
    if not candidates:
        candidates = (_agent(data.get("current_agent")),)
    return ProgramNodeResult(
        value={
            "accepted_candidate_count": len(candidates),
            "rejected_module_names": tuple(sorted(rejected)),
        },
        state_update={
            "module_archives": freeze_json(archives),
            "pending_evolution_agents": candidates,
        },
        next_node="evaluate_evolution",
        events=({
            "type": "agentsquare_modules_validated",
            "results": tuple(module_receipts),
        },),
        evidence_refs=tuple(sorted(set(evidence))),
    )


def _evaluate_many(
    evaluator: AgentSquareEvaluatorPort,
    candidates: tuple[JsonObject, ...],
) -> tuple[AgentSquareEvaluation, ...]:
    return tuple(
        evaluator.evaluate_agent(
            agent=row,
            episodes=AGENTSQUARE_FIDELITY.released_candidate_eval_episodes,
        )
        for row in candidates
    )


def _apply_evaluations(
    data: Mapping[str, JsonValue],
    results: tuple[AgentSquareEvaluation, ...],
) -> tuple[JsonObject, float, tuple[JsonObject, ...], int]:
    current = _agent(data.get("current_agent"))
    current_performance = _score(
        data.get("current_performance"),
        "current_performance",
    )
    tested = list(data.get("tested_cases", ()))
    for result in results:
        case = thaw_json(result.agent)
        assert isinstance(case, dict)
        case["performance"] = result.performance
        case["evaluation_digest"] = result.evaluation_digest
        tested.append(freeze_json(case))
        if result.performance > current_performance:
            current = result.agent
            current_performance = result.performance
    count = data.get("evaluation_count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("AgentSquare evaluation_count must be non-negative")
    return current, current_performance, tuple(tested), count + len(results)


def _evaluate_evolution(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    bound = _require_binding(binding)
    data = _state(request)
    candidates = _agents(data.get("pending_evolution_agents", ()))
    results = _evaluate_many(bound.evaluator, candidates)
    if any(not isinstance(row, AgentSquareEvaluation) for row in results):
        raise TypeError("AgentSquare evaluator returned invalid agent result")
    current, performance, tested, count = _apply_evaluations(data, results)
    evidence = tuple(sorted({
        ref for row in results for ref in row.evidence_refs
    }))
    artifacts = tuple(sorted({
        ref for row in results for ref in row.artifact_refs
    }))
    return ProgramNodeResult(
        value={
            "evaluated": len(results),
            "best_performance": performance,
        },
        state_update={
            "current_agent": current,
            "current_performance": performance,
            "tested_cases": tested,
            "evaluation_count": count,
        },
        next_node="recombine",
        events=({
            "type": "agentsquare_evolution_agents_evaluated",
            "count": len(results),
            "best_performance": performance,
        },),
        evidence_refs=evidence,
        artifact_refs=artifacts,
    )


def _recombine(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
    bound = _require_binding(binding)
    data = _state(request)
    candidates = bound.search_model.recombine(
        current_agent=_agent(data.get("current_agent")),
        module_archives=freeze_json(_archives(data.get("module_archives"))),
        tested_cases=tuple(data.get("tested_cases", ())),
    )
    candidates = tuple(
        row for row in _agents(candidates) if row.get("tooluse") == "None"
    )
    if not candidates:
        raise ValueError("AgentSquare recombination returned no ALFWorld candidates")
    return ProgramNodeResult(
        value={"candidate_count": len(candidates)},
        state_update={"pending_recombination_agents": candidates},
        next_node="predict",
        events=({
            "type": "agentsquare_agents_recombined",
            "candidate_count": len(candidates),
        },),
    )


def _predict(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
    bound = _require_binding(binding)
    data = _state(request)
    candidates = _agents(data.get("pending_recombination_agents", ()))
    predictions = tuple(
        _score(row, "prediction")
        for row in bound.search_model.predict(
            module_archives=freeze_json(_archives(data.get("module_archives"))),
            tested_cases=tuple(data.get("tested_cases", ())),
            candidates=candidates,
        )
    )
    if len(predictions) != len(candidates):
        raise ValueError("AgentSquare predictor cardinality drifted")
    best_index = max(range(len(predictions)), key=predictions.__getitem__)
    return ProgramNodeResult(
        value={
            "selected_index": best_index,
            "predicted_performance": predictions[best_index],
        },
        state_update={"pending_predictions": predictions},
        next_node="evaluate_recombined",
        events=({
            "type": "agentsquare_performance_predicted",
            "predictions": predictions,
            "selected_index": best_index,
        },),
    )


def _evaluate_recombined(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    bound = _require_binding(binding)
    data = _state(request)
    candidates = _agents(data.get("pending_recombination_agents", ()))
    predictions = tuple(data.get("pending_predictions", ()))
    if len(predictions) != len(candidates):
        raise ValueError("AgentSquare pending predictions drifted")
    best_index = max(range(len(predictions)), key=lambda i: float(predictions[i]))
    result = bound.evaluator.evaluate_agent(
        agent=candidates[best_index],
        episodes=AGENTSQUARE_FIDELITY.released_candidate_eval_episodes,
    )
    if not isinstance(result, AgentSquareEvaluation):
        raise TypeError("AgentSquare evaluator returned invalid recombined result")
    current, performance, tested, count = _apply_evaluations(data, (result,))
    return ProgramNodeResult(
        value={
            "actual_performance": result.performance,
            "best_performance": performance,
        },
        state_update={
            "current_agent": current,
            "current_performance": performance,
            "tested_cases": tested,
            "evaluation_count": count,
        },
        next_node="record_iteration",
        events=({
            "type": "agentsquare_recombined_agent_evaluated",
            "predicted_performance": predictions[best_index],
            "actual_performance": result.performance,
        },),
        evidence_refs=result.evidence_refs,
        artifact_refs=result.artifact_refs,
    )


def _record_iteration(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    _require_binding(binding)
    data = _state(request)
    iteration = data.get("iteration", 0)
    if type(iteration) is not int or iteration < 0:
        raise ValueError("AgentSquare iteration must be non-negative")
    iteration += 1
    history = tuple(data.get("best_history", ())) + ({
        "iteration": iteration,
        "agent": _agent(data.get("current_agent")),
        "performance": _score(
            data.get("current_performance"),
            "current_performance",
        ),
    },)
    finished = iteration >= AGENTSQUARE_FIDELITY.released_alfworld_search_iterations
    return ProgramNodeResult(
        value={"iteration": iteration, "finished": finished},
        state_update={
            "iteration": iteration,
            "best_history": history,
            "pending_modules": {},
            "pending_evolution_agents": (),
            "pending_recombination_agents": (),
            "pending_predictions": (),
        },
        next_node="finalize" if finished else "evolve",
        events=({
            "type": "agentsquare_iteration_recorded",
            "iteration": iteration,
            "best_performance": data.get("current_performance"),
        },),
    )


def _finalize(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
    bound = _require_binding(binding)
    data = _state(request)
    result_digest = canonical_digest({
        "optimization_id": data.get("optimization_id"),
        "fidelity_digest": AGENTSQUARE_FIDELITY.fidelity_digest,
        "binding_digest": bound.binding_digest,
        "iteration": data.get("iteration"),
        "current_agent": thaw_json(_agent(data.get("current_agent"))),
        "current_performance": data.get("current_performance"),
        "tested_case_count": len(tuple(data.get("tested_cases", ()))),
        "evaluation_count": data.get("evaluation_count"),
    })
    return ProgramNodeResult(
        value={
            "best_agent": _agent(data.get("current_agent")),
            "best_performance": data.get("current_performance"),
            "iterations": data.get("iteration"),
            "evaluation_count": data.get("evaluation_count"),
            "result_digest": result_digest,
        },
        state_update={"result_digest": result_digest},
        status=MachineStatus.COMPLETED,
        events=({
            "type": "agentsquare_optimization_finalized",
            "result_digest": result_digest,
            "best_performance": data.get("current_performance"),
        },),
    )


def build_agentsquare_alfworld_optimization_program() -> ResearchProgram:
    builder = OptimizationProgramBuilder.create(
        program_id="agentsquare.alfworld.later-official",
        version="1",
        state_schema="agentsquare.alfworld.optimization-state.v1",
        entrypoint="evolve",
    )
    builder.semantic(
        "evolve",
        OptimizationConcern.MUTATION,
        "agentsquare.module.evolve",
        next_node="validate_modules",
    )
    builder.semantic(
        "validate_modules",
        OptimizationConcern.EVALUATION,
        "agentsquare.module.validate",
        next_node="evaluate_evolution",
    )
    builder.semantic(
        "evaluate_evolution",
        OptimizationConcern.EVALUATION,
        "agentsquare.agent.evaluate-evolution",
        next_node="recombine",
    )
    builder.semantic(
        "recombine",
        OptimizationConcern.GENERATION,
        "agentsquare.agent.recombine",
        next_node="predict",
    )
    builder.semantic(
        "predict",
        OptimizationConcern.SELECTION,
        "agentsquare.performance.predict",
        next_node="evaluate_recombined",
    )
    builder.semantic(
        "evaluate_recombined",
        OptimizationConcern.EVALUATION,
        "agentsquare.agent.evaluate-recombined",
        next_node="record_iteration",
    )
    builder.semantic(
        "record_iteration",
        OptimizationConcern.BUDGET,
        "agentsquare.iteration.record",
        next_node="evolve",
    )
    builder.semantic(
        "finalize",
        OptimizationConcern.TERMINATION,
        "agentsquare.finalize",
    )
    return builder.build()


AGENTSQUARE_ALFWORLD_OPTIMIZATION_PROGRAM = (
    build_agentsquare_alfworld_optimization_program()
)


def _operation_digest(operation: str) -> str:
    return canonical_digest({
        "paper": "AgentSquare",
        "source_commit": AGENTSQUARE_FIDELITY.audited_commit,
        "operation": operation,
        "implementation_revision": 1,
    })


def agentsquare_alfworld_operations() -> tuple[ResearchHostOperation, ...]:
    rows = (
        ("agentsquare.module.evolve", _evolve),
        ("agentsquare.module.validate", _validate_modules),
        ("agentsquare.agent.evaluate-evolution", _evaluate_evolution),
        ("agentsquare.agent.recombine", _recombine),
        ("agentsquare.performance.predict", _predict),
        ("agentsquare.agent.evaluate-recombined", _evaluate_recombined),
        ("agentsquare.iteration.record", _record_iteration),
        ("agentsquare.finalize", _finalize),
    )
    return tuple(
        ResearchHostOperation(operation, handler, _operation_digest(operation))
        for operation, handler in rows
    )


def agentsquare_alfworld_host(journal: MachineJournalPort) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="agentsquare.alfworld.optimization",
        program=AGENTSQUARE_ALFWORLD_OPTIMIZATION_PROGRAM,
        operations=agentsquare_alfworld_operations(),
        journal=journal,
        max_steps=256,
        dependency_identity={
            "paper": "AgentSquare",
            "source_commit": AGENTSQUARE_FIDELITY.audited_commit,
            "fidelity_digest": AGENTSQUARE_FIDELITY.fidelity_digest,
            "benchmark": "ALFWorld",
        },
    )


def agentsquare_alfworld_instance_identity(
    *,
    binding: AgentSquareOptimizationBinding,
    initial_data: JsonObject,
) -> JsonObject:
    if not isinstance(binding, AgentSquareOptimizationBinding):
        raise TypeError("AgentSquare instance identity requires binding")
    return {
        "program_digest": AGENTSQUARE_ALFWORLD_OPTIMIZATION_PROGRAM.program_digest,
        "fidelity_digest": AGENTSQUARE_FIDELITY.fidelity_digest,
        "binding_digest": binding.binding_digest,
        "initial_data_digest": canonical_digest(initial_data),
    }


__all__ = [
    "AGENTSQUARE_ALFWORLD_OPTIMIZATION_PROGRAM",
    "AgentSquareEvaluation",
    "AgentSquareEvaluatorPort",
    "AgentSquareEvolutionProposal",
    "AgentSquareModuleEvaluation",
    "AgentSquareOptimizationBinding",
    "AgentSquareSearchModelPort",
    "agentsquare_alfworld_host",
    "agentsquare_alfworld_initial_data",
    "agentsquare_alfworld_instance_identity",
    "agentsquare_alfworld_operations",
    "build_agentsquare_alfworld_optimization_program",
]
