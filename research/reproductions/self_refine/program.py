from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
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

from .fidelity import SELF_REFINE_FIDELITY

_MODEL_AGENT_ID = "self-refine.model"
_MAX_ATTEMPTS = SELF_REFINE_FIDELITY.commongen_max_attempts


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"Self-Refine {field} must be text")
    return value


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"Self-Refine {field} must be a sequence")
    rows = tuple(_text(row, field) for row in value)
    if not rows:
        raise ValueError(f"Self-Refine {field} must be non-empty")
    return rows


def self_refine_commongen_initial_state(
    *,
    task_id: str,
    concepts: tuple[str, ...],
) -> JsonObject:
    return {
        "task_id": _text(task_id, "task_id"),
        "concepts": _strings(concepts, "concepts"),
        "attempt_index": 0,
        "history": (),
        "current_sentence": "",
        "accepted": False,
    }


def _generation_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "phase": "init",
        "task_id": request.state["task_id"],
        "concepts": request.state["concepts"],
        "temperature": SELF_REFINE_FIDELITY.commongen_temperature,
        "max_output_tokens": SELF_REFINE_FIDELITY.commongen_max_output_tokens,
        "stop_sequence": "###",
        "prompt_artifact": "data/prompt/commongen/init.jsonl",
    }


def _sentence(value: JsonValue) -> str:
    if isinstance(value, str):
        return _text(value, "sentence")
    if isinstance(value, Mapping):
        candidate = value.get("sentence", value.get("text"))
        if isinstance(candidate, str):
            return _text(candidate, "sentence")
    raise TypeError("Self-Refine model result must contain sentence text")


def _record_sentence(request: MethodNodeRequest) -> MethodNodeResult:
    sentence = _sentence(request.previous_value)
    return MethodNodeResult(
        value={"sentence": sentence},
        state_update={"current_sentence": sentence},
        next_node="feedback",
    )


def _feedback_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "phase": "feedback",
        "task_id": request.state["task_id"],
        "concepts": request.state["concepts"],
        "sentence": _text(request.state.get("current_sentence"), "current sentence"),
        "temperature": SELF_REFINE_FIDELITY.commongen_temperature,
        "max_output_tokens": SELF_REFINE_FIDELITY.commongen_max_output_tokens,
        "stop_sequence": "###",
        "prompt_artifact": "data/prompt/commongen/feedback.jsonl",
        "output_schema": {
            "concept_feedback": "comma-separated missing concepts or None",
            "commonsense_feedback": "feedback text or None",
        },
    }


def _feedback(value: JsonValue) -> tuple[tuple[str, ...], str]:
    if not isinstance(value, Mapping):
        raise TypeError("Self-Refine feedback result must be a mapping")
    raw_concepts = value.get("concept_feedback")
    commonsense = value.get("commonsense_feedback")
    if isinstance(raw_concepts, str):
        concept_feedback = tuple(
            item.strip()
            for item in raw_concepts.split(",")
            if item.strip()
        )
    elif isinstance(raw_concepts, Sequence) and not isinstance(
        raw_concepts, (str, bytes, bytearray)
    ):
        concept_feedback = tuple(_text(item, "concept feedback") for item in raw_concepts)
    else:
        raise TypeError("Self-Refine concept_feedback must be text or sequence")
    if not concept_feedback:
        concept_feedback = ("None",)
    return concept_feedback, _text(commonsense, "commonsense feedback")


def _feedback_is_none(concepts: tuple[str, ...], commonsense: str) -> bool:
    return (
        len(concepts) == 1
        and concepts[0].strip().lower() == "none"
        and commonsense.strip().lower() == "none"
    )


def _record_feedback(request: MethodNodeRequest) -> MethodNodeResult:
    concepts, commonsense = _feedback(request.previous_value)
    sentence = _text(request.state.get("current_sentence"), "current sentence")
    history = (
        *tuple(request.state.get("history", ())),
        freeze_json(
            {
                "sentence": sentence,
                "concept_feedback": concepts,
                "commonsense_feedback": commonsense,
            }
        ),
    )
    accepted = _feedback_is_none(concepts, commonsense)
    attempt_index = int(request.state.get("attempt_index", 0))
    exhausted = attempt_index + 1 >= _MAX_ATTEMPTS
    return MethodNodeResult(
        value={
            "accepted": accepted,
            "attempt": attempt_index + 1,
            "exhausted": exhausted,
        },
        state_update={
            "history": history,
            "accepted": accepted,
        },
        next_node="return" if accepted or exhausted else "refine",
        checkpoint=True,
        checkpoint_value={
            "attempt": attempt_index + 1,
            "accepted": accepted,
            "sentence": sentence,
        },
    )


def _refine_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "phase": "iterate",
        "task_id": request.state["task_id"],
        "concepts": request.state["concepts"],
        "sentence_to_feedback": tuple(request.state.get("history", ())),
        "temperature": SELF_REFINE_FIDELITY.commongen_temperature,
        "max_output_tokens": SELF_REFINE_FIDELITY.commongen_max_output_tokens,
        "stop_sequence": "\n\n###\n\n",
        "prompt_artifact": "data/prompt/commongen/iterate.jsonl",
    }


def _record_refinement(request: MethodNodeRequest) -> MethodNodeResult:
    sentence = _sentence(request.previous_value)
    attempt_index = int(request.state.get("attempt_index", 0)) + 1
    return MethodNodeResult(
        value={"sentence": sentence, "attempt_index": attempt_index},
        state_update={
            "current_sentence": sentence,
            "attempt_index": attempt_index,
        },
        next_node="feedback",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    history = tuple(request.state.get("history", ()))
    direct = history[0] if history else None
    final = history[-1] if history else None
    accepted = request.state.get("accepted") is True
    def component_success(row: object) -> tuple[bool, bool]:
        if not isinstance(row, Mapping):
            return False, False
        concepts = tuple(row.get("concept_feedback", ()))
        commonsense = str(row.get("commonsense_feedback", ""))
        concept_success = (
            len(concepts) == 1
            and str(concepts[0]).strip().lower() == "none"
        )
        commonsense_success = commonsense.strip().lower() == "none"
        return concept_success, commonsense_success

    direct_concept_success, direct_commonsense_success = component_success(direct)
    iter_concept_success, iter_commonsense_success = component_success(final)
    return MethodNodeResult(
        value={
            "task_id": request.state["task_id"],
            "concepts": request.state["concepts"],
            "sentence": request.state.get("current_sentence", ""),
            "accepted": accepted,
            "attempt_count": len(history),
            "history": history,
            "direct_concept_success": direct_concept_success,
            "direct_commonsense_success": direct_commonsense_success,
            "direct_success": direct_concept_success and direct_commonsense_success,
            "iter_concept_success": iter_concept_success,
            "iter_commonsense_success": iter_commonsense_success,
            "iter_success": iter_concept_success and iter_commonsense_success,
        }
    )


def build_self_refine_commongen_method_program() -> MethodProgram:
    configuration: JsonObject = {
        "source_commit": SELF_REFINE_FIDELITY.audited_commit,
        "mechanism": SELF_REFINE_FIDELITY.mechanism,
        "same_model_reused_across_roles": True,
        "task": "commongen",
        "max_attempts": _MAX_ATTEMPTS,
        "temperature": SELF_REFINE_FIDELITY.commongen_temperature,
        "max_output_tokens": SELF_REFINE_FIDELITY.commongen_max_output_tokens,
        "prompt_blobs": (
            SELF_REFINE_FIDELITY.commongen_init_prompt_blob,
            SELF_REFINE_FIDELITY.commongen_feedback_prompt_blob,
            SELF_REFINE_FIDELITY.commongen_iterate_prompt_blob,
        ),
        "stop_condition": SELF_REFINE_FIDELITY.commongen_stop_condition,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="self-refine",
            implementation_version=SELF_REFINE_FIDELITY.audited_commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="self-refine.commongen.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="generate")
    builder.agent(
        "generate",
        "self-refine.commongen.init",
        _MODEL_AGENT_ID,
        ("record_sentence",),
        view_handler=_generation_view,
        max_visits=1,
    )
    builder.compute(
        "record_sentence",
        "self-refine.sentence.record",
        _record_sentence,
        ("feedback",),
        max_visits=1,
    )
    builder.agent(
        "feedback",
        "self-refine.commongen.feedback",
        _MODEL_AGENT_ID,
        ("record_feedback",),
        view_handler=_feedback_view,
        max_visits=_MAX_ATTEMPTS,
    )
    builder.route(
        "record_feedback",
        "self-refine.feedback.record",
        _record_feedback,
        ("refine", "return"),
        max_visits=_MAX_ATTEMPTS,
    )
    builder.agent(
        "refine",
        "self-refine.commongen.iterate",
        _MODEL_AGENT_ID,
        ("record_refinement",),
        view_handler=_refine_view,
        max_visits=_MAX_ATTEMPTS - 1,
    )
    builder.compute(
        "record_refinement",
        "self-refine.refinement.record",
        _record_refinement,
        ("feedback",),
        max_visits=_MAX_ATTEMPTS - 1,
    )
    builder.return_node("return", "self-refine.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "self-refine.model-visible-history",
            "self-refine.feedback",
        ),
        metric_names=(
            "direct_concept_success",
            "direct_commonsense_success",
            "direct_success",
            "iter_concept_success",
            "iter_commonsense_success",
            "iter_success",
            "attempt_count",
        ),
        artifact_kinds=("self_refine_history", "commongen_prediction"),
    )


SELF_REFINE_COMMONGEN_METHOD_PROGRAM = build_self_refine_commongen_method_program()


__all__ = [
    "SELF_REFINE_COMMONGEN_METHOD_PROGRAM",
    "build_self_refine_commongen_method_program",
    "self_refine_commongen_initial_state",
]
