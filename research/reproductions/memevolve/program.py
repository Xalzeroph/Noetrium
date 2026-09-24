from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)
from noetrium_platform.research.experimentation.workbench.api import (
    candidate_program_capability_payload,
)

from .fidelity import MEMEVOLVE_FIDELITY


_ANALYZER = "memevolve.analyzer"
_MEMORY_GENERATOR = "memevolve.memory-generator"
_IMPLEMENTATION_GENERATOR = "memevolve.implementation-generator"
_CANDIDATE_EXECUTION = "workbench.candidate-program.execute"
_HOST_MAX_ROUNDS = 32
_HOST_MAX_CANDIDATES = 32
_HOST_MAX_EXECUTIONS = 2048


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"MemEvolve {field} must be non-empty text")
    return value.strip()


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"MemEvolve {field} must be an integer >= {minimum}")
    return value


def _sequence(value: object, field: str) -> tuple[JsonValue, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"MemEvolve {field} must be a sequence")
    return tuple(freeze_json(row) for row in value)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"MemEvolve {field} must be a mapping")
    return value


def _candidate(value: object) -> JsonObject:
    row = _mapping(value, "candidate")
    return {
        "name": _text(row.get("name"), "candidate name"),
        "memory_content": _text(row.get("memory_content"), "candidate memory_content"),
        "implementation_source": _text(
            row.get("implementation_source"),
            "candidate implementation_source",
        ),
    }


def memevolve_initial_state(
    *,
    base_candidate: Mapping[str, object],
    round_budget: int,
    candidate_count: int,
    finals_top_t: int,
) -> JsonObject:
    if round_budget > _HOST_MAX_ROUNDS:
        raise ValueError("MemEvolve round_budget exceeds host safety bound")
    if candidate_count > _HOST_MAX_CANDIDATES:
        raise ValueError("MemEvolve candidate_count exceeds host safety bound")
    if finals_top_t > candidate_count + 1:
        raise ValueError("MemEvolve finals_top_t exceeds tournament population")
    return {
        "base_candidate": _candidate(base_candidate),
        "round_budget": _integer(round_budget, "round_budget", minimum=1),
        "candidate_count": _integer(candidate_count, "candidate_count", minimum=1),
        "finals_top_t": _integer(finals_top_t, "finals_top_t", minimum=1),
        "round_index": 0,
        "candidate_index": 0,
        "current_memory_spec": {},
        "candidates": (),
        "tournament_results": (),
        "finalists": (),
        "final_results": (),
        "base_logs": (),
        "analysis": {},
        "candidate_execution_count": 0,
    }


def _execution_payload(candidate: Mapping[str, object], *, phase: str, index: int) -> JsonObject:
    row = _candidate(candidate)
    payload = dict(
        candidate_program_capability_payload(
            candidate_id=f"memevolve:{phase}:{index}:{row['name']}",
            generation=index,
            source_text=_text(row["implementation_source"], "implementation_source"),
            language="python",
            entrypoint="build_memory_system",
            interface_schema_id="memevolve.memory-system.v1",
        )
    )
    payload["phase"] = phase
    payload["memory_content"] = row["memory_content"]
    return freeze_json(payload)


def _prepare_base(request: MethodNodeRequest) -> MethodNodeResult:
    base = _mapping(request.state.get("base_candidate"), "base_candidate")
    return MethodNodeResult(
        value=_execution_payload(
            base,
            phase="collect_base_logs",
            index=_integer(request.state.get("round_index", 0), "round_index"),
        )
    )


def _record_base(request: MethodNodeRequest) -> MethodNodeResult:
    logs = list(_sequence(request.state.get("base_logs", ()), "base_logs"))
    logs.append(request.previous_value)
    count = _integer(
        request.state.get("candidate_execution_count", 0),
        "candidate_execution_count",
    )
    return MethodNodeResult(
        value={"base_logs_collected": len(logs)},
        state_update={
            "base_logs": tuple(logs),
            "candidate_execution_count": count + 1,
        },
    )


def _analyze_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "phase": MEMEVOLVE_FIDELITY.manual_phases[0],
        "round_index": request.state.get("round_index", 0),
        "base_candidate": request.state.get("base_candidate", {}),
        "base_logs": request.state.get("base_logs", ()),
        "evolves_memory_content": MEMEVOLVE_FIDELITY.evolves_memory_content,
        "evolves_memory_architecture": MEMEVOLVE_FIDELITY.evolves_memory_architecture,
    }


def _record_analysis(request: MethodNodeRequest) -> MethodNodeResult:
    analysis = _mapping(request.previous_value, "trajectory analysis")
    return MethodNodeResult(
        value={"analysis_recorded": True},
        state_update={
            "analysis": freeze_json(dict(analysis)),
            "candidate_index": 0,
            "candidates": (),
            "tournament_results": (),
            "finalists": (),
            "final_results": (),
        },
    )


def _memory_generator_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "phase": MEMEVOLVE_FIDELITY.manual_phases[1],
        "round_index": request.state.get("round_index", 0),
        "candidate_index": request.state.get("candidate_index", 0),
        "base_candidate": request.state.get("base_candidate", {}),
        "analysis": request.state.get("analysis", {}),
        "independence_contract": (
            "candidate generation sees base+analysis only; prior candidates are hidden"
        ),
        "output_fields": ("name", "memory_content", "architecture_spec"),
    }


def _record_memory_spec(request: MethodNodeRequest) -> MethodNodeResult:
    row = _mapping(request.previous_value, "memory-system proposal")
    spec = {
        "name": _text(row.get("name"), "memory-system name"),
        "memory_content": _text(row.get("memory_content"), "memory_content"),
        "architecture_spec": freeze_json(row.get("architecture_spec", {})),
    }
    return MethodNodeResult(
        value={"memory_system_generated": spec["name"]},
        state_update={"current_memory_spec": spec},
    )


def _implementation_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "phase": MEMEVOLVE_FIDELITY.manual_phases[2],
        "round_index": request.state.get("round_index", 0),
        "candidate_index": request.state.get("candidate_index", 0),
        "memory_system": request.state.get("current_memory_spec", {}),
        "output_contract": {
            "language": "python",
            "entrypoint": "build_memory_system",
        },
    }


def _record_implementation(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, Mapping):
        source = value.get("implementation_source", value.get("code"))
    else:
        source = value
    spec = _mapping(request.state.get("current_memory_spec"), "current_memory_spec")
    candidate = {
        "name": _text(spec.get("name"), "candidate name"),
        "memory_content": _text(spec.get("memory_content"), "candidate memory_content"),
        "implementation_source": _text(source, "implementation source"),
    }
    return MethodNodeResult(
        value={"implementation_created": candidate["name"]},
        state_update={"current_memory_spec": candidate},
    )


def _validate_candidate(request: MethodNodeRequest) -> MethodNodeResult:
    candidate = _candidate(request.state.get("current_memory_spec"))
    candidates = list(_sequence(request.state.get("candidates", ()), "candidates"))
    candidates.append(candidate)
    index = _integer(request.state.get("candidate_index", 0), "candidate_index") + 1
    count = _integer(request.state.get("candidate_count"), "candidate_count", minimum=1)
    return MethodNodeResult(
        value={
            "phase": MEMEVOLVE_FIDELITY.manual_phases[3],
            "candidate": candidate["name"],
            "validated": True,
        },
        state_update={
            "candidates": tuple(candidates),
            "candidate_index": index,
            "current_memory_spec": {},
        },
        next_node="generate_memory" if index < count else "prepare_tournament",
        checkpoint=True,
        checkpoint_value={"candidate_index": index, "candidate": candidate["name"]},
    )


def _tournament_population(request: MethodNodeRequest) -> tuple[JsonObject, ...]:
    base = _candidate(request.state.get("base_candidate"))
    candidates = tuple(
        _candidate(row)
        for row in _sequence(request.state.get("candidates", ()), "candidates")
    )
    return (base, *candidates)


def _prepare_tournament(request: MethodNodeRequest) -> MethodNodeResult:
    results = _sequence(request.state.get("tournament_results", ()), "tournament_results")
    population = _tournament_population(request)
    index = len(results)
    if index >= len(population):
        return MethodNodeResult(value={"tournament_complete": True}, next_node="select_finalists")
    return MethodNodeResult(
        value=_execution_payload(
            population[index],
            phase="same_task_tournament",
            index=index,
        ),
        next_node="execute_tournament",
    )


def _score(value: object) -> float:
    row = _mapping(value, "candidate execution result")
    score = row.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise TypeError("MemEvolve candidate execution result requires numeric score")
    return float(score)


def _record_tournament(request: MethodNodeRequest) -> MethodNodeResult:
    results = list(_sequence(request.state.get("tournament_results", ()), "tournament_results"))
    population = _tournament_population(request)
    index = len(results)
    result = freeze_json(
        {
            "candidate": population[index],
            "score": _score(request.previous_value),
            "execution": request.previous_value,
        }
    )
    results.append(result)
    count = _integer(
        request.state.get("candidate_execution_count", 0),
        "candidate_execution_count",
    )
    return MethodNodeResult(
        value={"tournament_index": index, "score": result["score"]},
        state_update={
            "tournament_results": tuple(results),
            "candidate_execution_count": count + 1,
        },
        next_node=(
            "prepare_tournament"
            if len(results) < len(population)
            else "select_finalists"
        ),
    )


def _select_finalists(request: MethodNodeRequest) -> MethodNodeResult:
    rows = [
        _mapping(row, "tournament result")
        for row in _sequence(request.state.get("tournament_results", ()), "tournament_results")
    ]
    top_t = _integer(request.state.get("finals_top_t"), "finals_top_t", minimum=1)
    ranked = sorted(rows, key=lambda row: float(row["score"]), reverse=True)
    finalists = tuple(freeze_json(row["candidate"]) for row in ranked[:top_t])
    return MethodNodeResult(
        value={"finalist_count": len(finalists)},
        state_update={"finalists": finalists, "final_results": ()},
    )


def _prepare_final(request: MethodNodeRequest) -> MethodNodeResult:
    finalists = tuple(
        _candidate(row)
        for row in _sequence(request.state.get("finalists", ()), "finalists")
    )
    results = _sequence(request.state.get("final_results", ()), "final_results")
    index = len(results)
    if index >= len(finalists):
        return MethodNodeResult(value={"finals_complete": True}, next_node="select_winner")
    return MethodNodeResult(
        value=_execution_payload(
            finalists[index],
            phase="extended_task_finals",
            index=index,
        ),
        next_node="execute_final",
    )


def _record_final(request: MethodNodeRequest) -> MethodNodeResult:
    finalists = tuple(
        _candidate(row)
        for row in _sequence(request.state.get("finalists", ()), "finalists")
    )
    results = list(_sequence(request.state.get("final_results", ()), "final_results"))
    index = len(results)
    result = freeze_json(
        {
            "candidate": finalists[index],
            "score": _score(request.previous_value),
            "execution": request.previous_value,
        }
    )
    results.append(result)
    count = _integer(
        request.state.get("candidate_execution_count", 0),
        "candidate_execution_count",
    )
    return MethodNodeResult(
        value={"final_index": index, "score": result["score"]},
        state_update={
            "final_results": tuple(results),
            "candidate_execution_count": count + 1,
        },
        next_node=(
            "prepare_final"
            if len(results) < len(finalists)
            else "select_winner"
        ),
    )


def _select_winner(request: MethodNodeRequest) -> MethodNodeResult:
    rows = [
        _mapping(row, "final result")
        for row in _sequence(request.state.get("final_results", ()), "final_results")
    ]
    if not rows:
        raise ValueError("MemEvolve finals must contain at least one result")
    winner = max(rows, key=lambda row: float(row["score"]))
    candidate = _candidate(winner["candidate"])
    round_index = _integer(request.state.get("round_index", 0), "round_index") + 1
    round_budget = _integer(request.state.get("round_budget"), "round_budget", minimum=1)
    return MethodNodeResult(
        value={
            "winner": candidate["name"],
            "score": winner["score"],
            "round_index": round_index,
        },
        state_update={
            "base_candidate": candidate,
            "round_index": round_index,
            "base_logs": (),
            "analysis": {},
            "candidate_index": 0,
            "candidates": (),
            "tournament_results": (),
            "finalists": (),
            "final_results": (),
        },
        next_node="return" if round_index >= round_budget else "prepare_base",
        checkpoint=True,
        checkpoint_value={
            "round_index": round_index,
            "winner": candidate["name"],
            "score": winner["score"],
        },
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={
            "winner": request.state.get("base_candidate", {}),
            "round_count": request.state.get("round_index", 0),
            "candidate_execution_count": request.state.get("candidate_execution_count", 0),
        }
    )


def build_memevolve_method_program() -> MethodProgram:
    f = MEMEVOLVE_FIDELITY
    configuration: JsonObject = {
        "source_commit": f.audited_code_commit,
        "code_root": f.code_root,
        "evolves_memory_content": f.evolves_memory_content,
        "evolves_memory_architecture": f.evolves_memory_architecture,
        "manual_phases": f.manual_phases,
        "round_process": f.round_process,
        "candidate_generation_independent": f.candidate_generation_independent,
        "same_task_tournament_required": f.same_task_tournament_required,
        "winner_becomes_next_round_base": f.winner_becomes_next_round_base,
        "checkpoint_on_auto_evolution_error": f.checkpoint_on_auto_evolution_error,
        "host_max_rounds": _HOST_MAX_ROUNDS,
        "host_max_candidates": _HOST_MAX_CANDIDATES,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="memevolve",
            implementation_version=f.audited_code_commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="memevolve.meta-evolution.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="prepare_base")
    builder.compute("prepare_base", "memevolve.base.prepare", _prepare_base, ("execute_base",), max_visits=_HOST_MAX_ROUNDS)
    builder.capability("execute_base", "memevolve.base.execute", _CANDIDATE_EXECUTION, ("record_base",), effect_class=EffectClass.RECONCILABLE, max_visits=_HOST_MAX_ROUNDS)
    builder.compute("record_base", "memevolve.base.record", _record_base, ("analyze",), max_visits=_HOST_MAX_ROUNDS)
    builder.agent("analyze", "memevolve.analyze-trajectories", _ANALYZER, ("record_analysis",), view_handler=_analyze_view, max_visits=_HOST_MAX_ROUNDS)
    builder.compute("record_analysis", "memevolve.analysis.record", _record_analysis, ("generate_memory",), max_visits=_HOST_MAX_ROUNDS)
    builder.agent("generate_memory", "memevolve.generate-memory-system", _MEMORY_GENERATOR, ("record_memory_spec",), view_handler=_memory_generator_view, max_visits=_HOST_MAX_ROUNDS * _HOST_MAX_CANDIDATES)
    builder.compute("record_memory_spec", "memevolve.memory-system.record", _record_memory_spec, ("create_implementation",), max_visits=_HOST_MAX_ROUNDS * _HOST_MAX_CANDIDATES)
    builder.agent("create_implementation", "memevolve.create-implementation", _IMPLEMENTATION_GENERATOR, ("record_implementation",), view_handler=_implementation_view, max_visits=_HOST_MAX_ROUNDS * _HOST_MAX_CANDIDATES)
    builder.compute("record_implementation", "memevolve.implementation.record", _record_implementation, ("validate_candidate",), max_visits=_HOST_MAX_ROUNDS * _HOST_MAX_CANDIDATES)
    builder.route("validate_candidate", "memevolve.validate-system", _validate_candidate, ("generate_memory", "prepare_tournament"), max_visits=_HOST_MAX_ROUNDS * _HOST_MAX_CANDIDATES)
    builder.route("prepare_tournament", "memevolve.tournament.prepare", _prepare_tournament, ("execute_tournament", "select_finalists"), max_visits=_HOST_MAX_EXECUTIONS)
    builder.capability("execute_tournament", "memevolve.tournament.execute", _CANDIDATE_EXECUTION, ("record_tournament",), effect_class=EffectClass.RECONCILABLE, max_visits=_HOST_MAX_EXECUTIONS)
    builder.route("record_tournament", "memevolve.tournament.record", _record_tournament, ("prepare_tournament", "select_finalists"), max_visits=_HOST_MAX_EXECUTIONS)
    builder.compute("select_finalists", "memevolve.finals.select", _select_finalists, ("prepare_final",), max_visits=_HOST_MAX_ROUNDS)
    builder.route("prepare_final", "memevolve.finals.prepare", _prepare_final, ("execute_final", "select_winner"), max_visits=_HOST_MAX_EXECUTIONS)
    builder.capability("execute_final", "memevolve.finals.execute", _CANDIDATE_EXECUTION, ("record_final",), effect_class=EffectClass.RECONCILABLE, max_visits=_HOST_MAX_EXECUTIONS)
    builder.route("record_final", "memevolve.finals.record", _record_final, ("prepare_final", "select_winner"), max_visits=_HOST_MAX_EXECUTIONS)
    builder.route("select_winner", "memevolve.winner.select", _select_winner, ("prepare_base", "return"), max_visits=_HOST_MAX_ROUNDS)
    builder.return_node("return", "memevolve.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(_CANDIDATE_EXECUTION,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "memevolve.base-logs",
            "memevolve.candidate-lineage",
            "memevolve.same-task-tournament",
            "memevolve.extended-task-finals",
            "workbench.candidate-execution",
        ),
        metric_names=(
            "memory_score",
            "round_count",
            "candidate_execution_count",
        ),
        artifact_kinds=(
            "memevolve_memory_system",
            "memevolve_candidate_implementation",
            "memevolve_tournament",
        ),
    )


MEMEVOLVE_METHOD_PROGRAM = build_memevolve_method_program()


__all__ = [
    "MEMEVOLVE_METHOD_PROGRAM",
    "build_memevolve_method_program",
    "memevolve_initial_state",
]
