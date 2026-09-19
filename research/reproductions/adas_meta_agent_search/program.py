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
from noetrium_platform.research.experimentation.workbench.runtime import (
    candidate_program_capability_payload,
)

from .fidelity import ADAS_META_AGENT_SEARCH_FIDELITY

_META_AGENT_ID = "adas.meta-agent"
_CANDIDATE_EXECUTION_CAPABILITY = "workbench.candidate-program.execute"
_REQUIRED_MEASUREMENTS = (
    "mean_accuracy",
    "fitness_median",
    "fitness_ci_lower",
    "fitness_ci_upper",
)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"ADAS {field} must be non-empty text")
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"ADAS {field} must be a non-negative integer")
    return value


def _sequence(value: object, field: str) -> tuple[JsonValue, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"ADAS {field} must be a sequence")
    return tuple(freeze_json(row) for row in value)


def _candidate(value: object) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError("ADAS meta-agent result must be a mapping")
    return {
        "thought": _text(value.get("thought"), "candidate thought"),
        "name": _text(value.get("name"), "candidate name"),
        "code": _text(value.get("code"), "candidate code"),
        **(
            {"reflection": _text(value.get("reflection"), "candidate reflection")}
            if isinstance(value.get("reflection"), str) and value.get("reflection").strip()
            else {}
        ),
        **(
            {"debug_thought": _text(value.get("debug_thought"), "candidate debug_thought")}
            if isinstance(value.get("debug_thought"), str) and value.get("debug_thought").strip()
            else {}
        ),
    }


def _archive_row(value: object) -> JsonObject:
    candidate = _candidate(value)
    row: JsonObject = {
        "thought": candidate["thought"],
        "name": candidate["name"],
        "code": candidate["code"],
    }
    if isinstance(value, Mapping):
        fitness = value.get("fitness")
        generation = value.get("generation")
        if isinstance(fitness, str) and fitness.strip():
            row["fitness"] = fitness
        if isinstance(generation, (str, int)) and not isinstance(generation, bool):
            row["generation"] = generation
    return row


def adas_mgsm_initial_state(
    initial_archive: tuple[Mapping[str, object], ...],
) -> JsonObject:
    fidelity = ADAS_META_AGENT_SEARCH_FIDELITY
    if type(initial_archive) is not tuple or len(initial_archive) != len(
        fidelity.initial_archive_names
    ):
        raise ValueError("ADAS MGSM initial archive requires exactly seven seed agents")
    rows = tuple(_archive_row(row) for row in initial_archive)
    names = tuple(_text(row.get("name"), "initial archive name") for row in rows)
    if names != fidelity.initial_archive_names:
        raise ValueError(
            f"ADAS MGSM initial archive names drifted: expected={fidelity.initial_archive_names!r}"
        )
    return {
        "archive": rows,
        "initial_eval_index": 0,
        "generation_index": 0,
        "current_candidate": {},
        "execution_attempt": 0,
        "last_execution_error": "",
        "successful_generations": 0,
        "failed_generations": 0,
        "candidate_evidence": (),
        "fitness_projections": (),
    }


def _measurements(payload: Mapping[str, object]) -> dict[str, tuple[float, str]]:
    raw = payload.get("measurements", ())
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise TypeError("ADAS candidate execution measurements must be a sequence")
    result: dict[str, tuple[float, str]] = {}
    for row in raw:
        if not isinstance(row, Mapping):
            raise TypeError("ADAS candidate measurement row must be a mapping")
        measurement_id = _text(row.get("measurement_id"), "measurement_id")
        scalar = row.get("scalar")
        record_digest = _text(row.get("record_digest"), "measurement record_digest")
        if isinstance(scalar, bool) or not isinstance(scalar, (int, float)):
            raise TypeError("ADAS candidate measurement scalar must be numeric")
        result[measurement_id] = (float(scalar), record_digest)
    return result


def _fitness_text(measurements: Mapping[str, tuple[float, str]]) -> str:
    missing = tuple(row for row in _REQUIRED_MEASUREMENTS if row not in measurements)
    if missing:
        raise ValueError(f"ADAS candidate execution missing fitness measurements: {missing!r}")
    lower = measurements["fitness_ci_lower"][0] * 100.0
    upper = measurements["fitness_ci_upper"][0] * 100.0
    median = measurements["fitness_median"][0] * 100.0
    return (
        "95% Bootstrap Confidence Interval: "
        f"({lower:.1f}%, {upper:.1f}%), Median: {median:.1f}%"
    )


def _execution_payload(value: JsonValue) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("ADAS candidate execution result must be a mapping")
    return value


def _candidate_execution_request(
    *,
    candidate: Mapping[str, JsonValue],
    candidate_id: str,
    generation: int,
) -> JsonObject:
    return freeze_json(
        candidate_program_capability_payload(
            candidate_id=candidate_id,
            generation=generation,
            source_text=_text(candidate.get("code"), "candidate code"),
            language="python",
            entrypoint="forward",
            interface_schema_id="adas.agent-forward.task-info.v1",
        )
    )


def _prepare_initial_execution(request: MethodNodeRequest) -> MethodNodeResult:
    archive = _sequence(request.state.get("archive", ()), "archive")
    index = _integer(request.state.get("initial_eval_index", 0), "initial_eval_index")
    if index >= len(archive):
        return MethodNodeResult(value={"initial_archive_complete": True}, next_node="proposal")
    row = archive[index]
    if not isinstance(row, Mapping):
        raise TypeError("ADAS archive rows must be mappings")
    if isinstance(row.get("fitness"), str) and row.get("fitness").strip():
        return MethodNodeResult(
            value={"initial_candidate_already_evaluated": index},
            state_update={"initial_eval_index": index + 1},
            next_node="prepare_initial",
        )
    return MethodNodeResult(
        value=_candidate_execution_request(
            candidate=row,
            candidate_id=f"adas:mgsm:initial:{index}",
            generation=0,
        ),
        next_node="execute_initial",
    )


def _record_evidence(
    state: Mapping[str, JsonValue],
    *,
    candidate_name: str,
    generation: int | str,
    payload: Mapping[str, object],
    measurements: Mapping[str, tuple[float, str]] | None,
) -> tuple[tuple[JsonValue, ...], tuple[JsonValue, ...]]:
    evidence = list(_sequence(state.get("candidate_evidence", ()), "candidate_evidence"))
    evidence.append(
        {
            "candidate_name": candidate_name,
            "generation": generation,
            "candidate_digest": payload.get("candidate_digest"),
            "source_artifact_id": payload.get("source_artifact_id"),
            "source_content_sha256": payload.get("source_content_sha256"),
            "execution_receipt_digest": payload.get("execution_receipt_digest"),
            "status": payload.get("status"),
            "failure_code": payload.get("failure_code"),
            "measurement_record_digests": payload.get("measurement_record_digests", ()),
            "evidence_digests": payload.get("evidence_digests", ()),
            "isolation_evidence_digests": payload.get("isolation_evidence_digests", ()),
        }
    )
    projections = list(
        _sequence(state.get("fitness_projections", ()), "fitness_projections")
    )
    if measurements is not None:
        projections.append(
            {
                "candidate_name": candidate_name,
                "generation": generation,
                "mean_accuracy": measurements["mean_accuracy"][0],
                "fitness_median": measurements["fitness_median"][0],
                "fitness_ci_lower": measurements["fitness_ci_lower"][0],
                "fitness_ci_upper": measurements["fitness_ci_upper"][0],
            }
        )
    return tuple(evidence), tuple(projections)


def _record_initial_execution(request: MethodNodeRequest) -> MethodNodeResult:
    archive = list(_sequence(request.state.get("archive", ()), "archive"))
    index = _integer(request.state.get("initial_eval_index", 0), "initial_eval_index")
    row = archive[index]
    if not isinstance(row, Mapping):
        raise TypeError("ADAS archive rows must be mappings")
    payload = _execution_payload(request.previous_value)
    status = _text(payload.get("status"), "candidate execution status")
    measurements = _measurements(payload) if status == "succeeded" else None

    updated = dict(row)
    updated["generation"] = "initial"
    if measurements is not None:
        updated["fitness"] = _fitness_text(measurements)
    archive[index] = freeze_json(updated)
    evidence, projections = _record_evidence(
        request.state,
        candidate_name=_text(row.get("name"), "initial candidate name"),
        generation="initial",
        payload=payload,
        measurements=measurements,
    )
    next_index = index + 1
    return MethodNodeResult(
        value={"initial_candidate": index, "status": status},
        state_update={
            "archive": tuple(archive),
            "initial_eval_index": next_index,
            "candidate_evidence": evidence,
            "fitness_projections": projections,
        },
        next_node="prepare_initial" if next_index < len(archive) else "proposal",
    )


def _proposal_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "phase": "proposal",
        "generation": _integer(request.state.get("generation_index", 0), "generation_index") + 1,
        "archive": _sequence(request.state.get("archive", ()), "archive"),
        "output_fields": ("thought", "name", "code"),
        "temperature": ADAS_META_AGENT_SEARCH_FIDELITY.meta_temperature,
        "max_output_tokens": ADAS_META_AGENT_SEARCH_FIDELITY.meta_max_output_tokens,
        "benchmark": "mgsm",
    }


def _record_proposal(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={"proposal": True},
        state_update={
            "current_candidate": _candidate(request.previous_value),
            "execution_attempt": 0,
            "last_execution_error": "",
        },
        next_node="reflection_1",
    )


def _reflection_view(request: MethodNodeRequest, *, pass_index: int) -> JsonObject:
    archive = _sequence(request.state.get("archive", ()), "archive")
    generation_index = _integer(
        request.state.get("generation_index", 0),
        "generation_index",
    )
    previous = archive[-1] if generation_index > 0 and archive else None
    return {
        "phase": f"reflection_{pass_index}",
        "reflection_pass": pass_index,
        "generation": generation_index + 1,
        "candidate": request.state.get("current_candidate", {}),
        "previous_agent": previous,
        "archive_size": len(archive),
        "output_fields": ("reflection", "thought", "name", "code"),
        "temperature": ADAS_META_AGENT_SEARCH_FIDELITY.meta_temperature,
        "max_output_tokens": ADAS_META_AGENT_SEARCH_FIDELITY.meta_max_output_tokens,
    }


def _reflection_1_view(request: MethodNodeRequest) -> JsonObject:
    return _reflection_view(request, pass_index=1)


def _reflection_2_view(request: MethodNodeRequest) -> JsonObject:
    return _reflection_view(request, pass_index=2)


def _record_reflection_1(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={"reflection_pass": 1},
        state_update={"current_candidate": _candidate(request.previous_value)},
        next_node="reflection_2",
    )


def _record_reflection_2(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={"reflection_pass": 2},
        state_update={"current_candidate": _candidate(request.previous_value)},
        next_node="prepare_execution",
    )


def _prepare_execution(request: MethodNodeRequest) -> MethodNodeResult:
    candidate = request.state.get("current_candidate")
    if not isinstance(candidate, Mapping):
        raise TypeError("ADAS current candidate must be a mapping")
    generation = _integer(
        request.state.get("generation_index", 0),
        "generation_index",
    ) + 1
    return MethodNodeResult(
        value=_candidate_execution_request(
            candidate=candidate,
            candidate_id=f"adas:mgsm:generation:{generation}",
            generation=generation,
        )
    )


def _execution_failure_text(
    payload: Mapping[str, object],
    measurements: Mapping[str, tuple[float, str]] | None,
) -> str:
    if payload.get("status") != "succeeded":
        code = payload.get("failure_code")
        return f"candidate execution failed: {code or 'unknown'}"
    assert measurements is not None
    mean = measurements["mean_accuracy"][0]
    return (
        "candidate evaluation accuracy below search threshold: "
        f"{mean:.6f} < {ADAS_META_AGENT_SEARCH_FIDELITY.low_accuracy_debug_threshold:.6f}"
    )


def _record_execution(request: MethodNodeRequest) -> MethodNodeResult:
    payload = _execution_payload(request.previous_value)
    status = _text(payload.get("status"), "candidate execution status")
    measurements = _measurements(payload) if status == "succeeded" else None
    accepted = (
        measurements is not None
        and measurements["mean_accuracy"][0]
        >= ADAS_META_AGENT_SEARCH_FIDELITY.low_accuracy_debug_threshold
    )
    if accepted:
        candidate = request.state.get("current_candidate")
        if not isinstance(candidate, Mapping):
            raise TypeError("ADAS current candidate must be a mapping")
        generation = _integer(
            request.state.get("generation_index", 0),
            "generation_index",
        ) + 1
        archive = list(_sequence(request.state.get("archive", ()), "archive"))
        cleaned = _archive_row(candidate)
        cleaned["fitness"] = _fitness_text(measurements)
        cleaned["generation"] = generation
        archive.append(freeze_json(cleaned))
        evidence, projections = _record_evidence(
            request.state,
            candidate_name=_text(cleaned.get("name"), "candidate name"),
            generation=generation,
            payload=payload,
            measurements=measurements,
        )
        next_generation = generation
        return MethodNodeResult(
            value={"accepted_generation": generation},
            state_update={
                "archive": tuple(archive),
                "generation_index": next_generation,
                "successful_generations": _integer(
                    request.state.get("successful_generations", 0),
                    "successful_generations",
                )
                + 1,
                "execution_attempt": 0,
                "last_execution_error": "",
                "candidate_evidence": evidence,
                "fitness_projections": projections,
            },
            next_node=(
                "return"
                if next_generation >= ADAS_META_AGENT_SEARCH_FIDELITY.generation_budget
                else "proposal"
            ),
            checkpoint=True,
            checkpoint_value={
                "generation": generation,
                "candidate_name": cleaned["name"],
                "fitness": cleaned["fitness"],
            },
        )

    attempt = _integer(
        request.state.get("execution_attempt", 0),
        "execution_attempt",
    ) + 1
    candidate = request.state.get("current_candidate")
    if not isinstance(candidate, Mapping):
        raise TypeError("ADAS current candidate must be a mapping")
    evidence, projections = _record_evidence(
        request.state,
        candidate_name=_text(candidate.get("name"), "candidate name"),
        generation=_integer(
            request.state.get("generation_index", 0),
            "generation_index",
        )
        + 1,
        payload=payload,
        measurements=measurements,
    )
    return MethodNodeResult(
        value={"accepted": False, "execution_attempt": attempt},
        state_update={
            "execution_attempt": attempt,
            "last_execution_error": _execution_failure_text(payload, measurements),
            "candidate_evidence": evidence,
            "fitness_projections": projections,
        },
        next_node="debug",
    )


def _debug_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "phase": "debug",
        "generation": _integer(
            request.state.get("generation_index", 0),
            "generation_index",
        )
        + 1,
        "execution_attempt": _integer(
            request.state.get("execution_attempt", 0),
            "execution_attempt",
        ),
        "candidate": request.state.get("current_candidate", {}),
        "error": _text(
            request.state.get("last_execution_error"),
            "last_execution_error",
        ),
        "instruction": (
            "Carefully consider where the latest implementation failed. "
            "Repeat the previous thought in 'thought', put debugging reasoning "
            "in 'debug_thought', and return a corrected 'code'."
        ),
        "output_fields": ("thought", "debug_thought", "name", "code"),
        "temperature": ADAS_META_AGENT_SEARCH_FIDELITY.meta_temperature,
        "max_output_tokens": ADAS_META_AGENT_SEARCH_FIDELITY.meta_max_output_tokens,
    }


def _record_debug(request: MethodNodeRequest) -> MethodNodeResult:
    attempt = _integer(
        request.state.get("execution_attempt", 0),
        "execution_attempt",
    )
    return MethodNodeResult(
        value={"debug_regeneration": attempt},
        state_update={"current_candidate": _candidate(request.previous_value)},
        next_node=(
            "prepare_execution"
            if attempt < ADAS_META_AGENT_SEARCH_FIDELITY.candidate_execution_attempt_budget
            else "skip_generation"
        ),
    )


def _skip_generation(request: MethodNodeRequest) -> MethodNodeResult:
    next_generation = _integer(
        request.state.get("generation_index", 0),
        "generation_index",
    ) + 1
    return MethodNodeResult(
        value={"skipped_generation": next_generation},
        state_update={
            "generation_index": next_generation,
            "failed_generations": _integer(
                request.state.get("failed_generations", 0),
                "failed_generations",
            )
            + 1,
            "execution_attempt": 0,
            "last_execution_error": "",
            "current_candidate": {},
        },
        next_node=(
            "return"
            if next_generation >= ADAS_META_AGENT_SEARCH_FIDELITY.generation_budget
            else "proposal"
        ),
        checkpoint=True,
        checkpoint_value={
            "generation": next_generation,
            "skipped": True,
        },
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    projections = _sequence(
        request.state.get("fitness_projections", ()),
        "fitness_projections",
    )
    valid = [
        row
        for row in projections
        if isinstance(row, Mapping)
        and isinstance(row.get("fitness_median"), (int, float))
        and not isinstance(row.get("fitness_median"), bool)
    ]
    best = (
        max(valid, key=lambda row: float(row["fitness_median"]))
        if valid
        else None
    )
    archive = _sequence(request.state.get("archive", ()), "archive")
    return MethodNodeResult(
        value={
            "generation_slots": _integer(
                request.state.get("generation_index", 0),
                "generation_index",
            ),
            "successful_generations": _integer(
                request.state.get("successful_generations", 0),
                "successful_generations",
            ),
            "failed_generations": _integer(
                request.state.get("failed_generations", 0),
                "failed_generations",
            ),
            "archive_size": len(archive),
            "best_validation_accuracy": (
                0.0 if best is None else float(best["mean_accuracy"])
            ),
            "best_fitness_median": (
                0.0 if best is None else float(best["fitness_median"])
            ),
            "best_candidate_name": (
                None if best is None else best.get("candidate_name")
            ),
            "archive": archive,
            "candidate_evidence": request.state.get("candidate_evidence", ()),
        }
    )


def build_adas_mgsm_method_program() -> MethodProgram:
    fidelity = ADAS_META_AGENT_SEARCH_FIDELITY
    configuration: JsonObject = {
        "source_commit": fidelity.audited_commit,
        "source_artifact": fidelity.source_artifact,
        "benchmark": fidelity.benchmark,
        "meta_model": fidelity.meta_model,
        "candidate_default_model": fidelity.candidate_default_model,
        "reflection_passes": fidelity.reflection_passes_per_generation,
        "generation_budget": fidelity.generation_budget,
        "candidate_execution_attempt_budget": fidelity.candidate_execution_attempt_budget,
        "validation_size": fidelity.validation_size,
        "test_size": fidelity.test_size,
        "shuffle_seed": fidelity.shuffle_seed,
        "low_accuracy_debug_threshold": fidelity.low_accuracy_debug_threshold,
        "bootstrap_samples": fidelity.bootstrap_samples,
        "bootstrap_confidence_level": fidelity.bootstrap_confidence_level,
        "ineffective_generation_decrement": fidelity.ineffective_generation_decrement,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="adas-meta-agent-search",
            implementation_version=fidelity.audited_commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="adas.meta-agent-search.mgsm.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    generations = fidelity.generation_budget
    execution_limit = len(fidelity.initial_archive_names) + (
        generations * fidelity.candidate_execution_attempt_budget
    )
    builder = MethodProgramBuilder(identity, entrypoint="prepare_initial")
    builder.route(
        "prepare_initial",
        "adas.initial-archive.prepare",
        _prepare_initial_execution,
        ("execute_initial", "prepare_initial", "proposal"),
        max_visits=len(fidelity.initial_archive_names) + 1,
    )
    builder.capability(
        "execute_initial",
        "adas.initial-archive.execute",
        _CANDIDATE_EXECUTION_CAPABILITY,
        ("record_initial",),
        effect_class=EffectClass.IDEMPOTENT,
        max_visits=len(fidelity.initial_archive_names),
        evidence_obligations=("candidate.execution.receipt",),
    )
    builder.compute(
        "record_initial",
        "adas.initial-archive.record",
        _record_initial_execution,
        ("prepare_initial", "proposal"),
        max_visits=len(fidelity.initial_archive_names),
    )
    builder.agent(
        "proposal",
        "adas.meta.propose",
        _META_AGENT_ID,
        ("record_proposal",),
        view_handler=_proposal_view,
        max_visits=generations,
    )
    builder.compute(
        "record_proposal",
        "adas.meta.proposal.record",
        _record_proposal,
        ("reflection_1",),
        max_visits=generations,
    )
    builder.agent(
        "reflection_1",
        "adas.meta.reflect-1",
        _META_AGENT_ID,
        ("record_reflection_1",),
        view_handler=_reflection_1_view,
        max_visits=generations,
    )
    builder.compute(
        "record_reflection_1",
        "adas.meta.reflect-1.record",
        _record_reflection_1,
        ("reflection_2",),
        max_visits=generations,
    )
    builder.agent(
        "reflection_2",
        "adas.meta.reflect-2",
        _META_AGENT_ID,
        ("record_reflection_2",),
        view_handler=_reflection_2_view,
        max_visits=generations,
    )
    builder.compute(
        "record_reflection_2",
        "adas.meta.reflect-2.record",
        _record_reflection_2,
        ("prepare_execution",),
        max_visits=generations,
    )
    builder.compute(
        "prepare_execution",
        "adas.candidate.prepare",
        _prepare_execution,
        ("execute",),
        max_visits=generations * fidelity.candidate_execution_attempt_budget,
    )
    builder.capability(
        "execute",
        "adas.candidate.execute",
        _CANDIDATE_EXECUTION_CAPABILITY,
        ("record_execution",),
        effect_class=EffectClass.IDEMPOTENT,
        max_visits=execution_limit,
        evidence_obligations=("candidate.execution.receipt",),
    )
    builder.route(
        "record_execution",
        "adas.candidate.result",
        _record_execution,
        ("proposal", "debug", "return"),
        max_visits=execution_limit,
    )
    builder.agent(
        "debug",
        "adas.meta.debug",
        _META_AGENT_ID,
        ("record_debug",),
        view_handler=_debug_view,
        max_visits=generations * fidelity.candidate_execution_attempt_budget,
    )
    builder.route(
        "record_debug",
        "adas.meta.debug.record",
        _record_debug,
        ("prepare_execution", "skip_generation"),
        max_visits=generations * fidelity.candidate_execution_attempt_budget,
    )
    builder.route(
        "skip_generation",
        "adas.generation.skip",
        _skip_generation,
        ("proposal", "return"),
        max_visits=generations,
    )
    builder.return_node("return", "adas.search.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(_CANDIDATE_EXECUTION_CAPABILITY,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "adas.search-archive",
            "candidate.source-artifact",
            "candidate.execution.receipt",
            "candidate.measurement-records",
            "candidate.isolation-evidence",
        ),
        metric_names=(
            "archive_size",
            "successful_generation_count",
            "failed_generation_count",
            "best_validation_accuracy",
            "best_fitness_median",
        ),
        artifact_kinds=("adas_search_archive", "candidate_program_source"),
    )


ADAS_MGSM_METHOD_PROGRAM = build_adas_mgsm_method_program()

__all__ = [
    "ADAS_MGSM_METHOD_PROGRAM",
    "adas_mgsm_initial_state",
    "build_adas_mgsm_method_program",
]
