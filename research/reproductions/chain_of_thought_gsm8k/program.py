from __future__ import annotations

from research.reproductions._support import (
    JsonObject,
    JsonValue,
    MethodCall,
    canonical_digest,
    freeze_json,
    method_event,
    require_sha256,
    thaw_json,
)
from research.reproductions._support import JsonObject, JsonValue, canonical_digest

from collections.abc import Mapping




from .fidelity import CHAIN_OF_THOUGHT_GSM8K_FIDELITY
from .prompt import (
    COT_GSM8K_PROMPT_BUNDLE_ID,
    COT_GSM8K_PROMPT_DIGEST,
    render_chain_of_thought_gsm8k_prompt,
)

_REASONER = "cot.reasoner"


def chain_of_thought_gsm8k_initial_state(*, task_id: str, question: str) -> JsonObject:
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("CoT task_id is required")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("CoT GSM8K question is required")
    return {
        "task_id": task_id,
        "question": question,
        "completion": "",
    }


def _reasoner_view(request: MethodCall) -> JsonObject:
    f = CHAIN_OF_THOUGHT_GSM8K_FIDELITY
    question = request.state.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("CoT method state requires question")
    return {
        "task_id": request.state.get("task_id"),
        "question": question,
        "prompt_mode": f.prompt_mode,
        "prompt_bundle": COT_GSM8K_PROMPT_BUNDLE_ID,
        "prompt_digest": COT_GSM8K_PROMPT_DIGEST,
        "prompt": render_chain_of_thought_gsm8k_prompt(question),
        "exemplar_count": f.exemplar_count,
        "exemplar_source": f.exemplar_source,
        "decoding": f.decoding,
        "samples": f.samples_per_task,
    }


def _completion(value: JsonValue) -> str:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, Mapping):
        row = value.get("completion", value.get("text"))
        if isinstance(row, str) and row.strip():
            return row
    raise TypeError("CoT reasoner result must contain non-empty completion text")


def _record_completion(request: MethodCall) -> MethodNodeResult:
    text = _completion(request.previous_value)
    return dict(
        value={"completion": text},
        state_update={"completion": text},
        events=(
            method_event(
                "cot.reasoning-completion",
                {"completion_digest": canonical_digest(text)},
            ),
        ),
        next_node="return",
    )


def _return_result(request: MethodCall) -> MethodNodeResult:
    completion = request.state.get("completion")
    if not isinstance(completion, str) or not completion.strip():
        raise ValueError("CoT completion is missing")
    return dict(
        value={
            "task_id": request.state.get("task_id"),
            "completion": completion,
            "reasoning_path_count": 1,
        }
    )


def build_chain_of_thought_gsm8k_method_program(method, ) -> None:
    f = CHAIN_OF_THOUGHT_GSM8K_FIDELITY
    configuration: JsonObject = {
        "publication_lane_digest": f.publication.lane_digest,
        "benchmark_id": f.benchmark_id,
        "benchmark_split": f.benchmark_split,
        "exemplar_count": f.exemplar_count,
        "exemplar_source": f.exemplar_source,
        "prompt_mode": f.prompt_mode,
        "prompt_bundle": COT_GSM8K_PROMPT_BUNDLE_ID,
        "prompt_digest": COT_GSM8K_PROMPT_DIGEST,
        "decoding": f.decoding,
        "samples_per_task": f.samples_per_task,
        "calculator_enabled": f.calculator_enabled,
    }

    builder = method
    builder.agent(
        "reason",
        "cot.gsm8k.reason",
        _REASONER,
        ("record",),
        view=_reasoner_view,
    )
    builder.compute(
        "record",
        "cot.gsm8k.record-completion",
        _record_completion,
        ("return",),
    )
    builder.return_node("return", "cot.gsm8k.result", _return_result)
    builder.configure(configuration)
    builder.policy(
        execution='effect_recorded',
        evidence=("cot.reasoning-completion", "model.invocation"),
        metrics=("task_success", "model_call_count"),
        artifacts=("cot_completion",),
    )
    return builder


METHOD_CONFIGURER = build_chain_of_thought_gsm8k_method_program
METHOD_ENTRYPOINT = "reason"
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = [
    'build_chain_of_thought_gsm8k_method_program',
    'chain_of_thought_gsm8k_initial_state',
    'METHOD_CONFIGURER',
    'METHOD_ENTRYPOINT',
    'METHOD_CONFIGURER_ARGS',
    'METHOD_CONFIGURER_KWARGS',
]

METHOD_SPEC = {"method_id": 'chain-of-thought', "version": "paper-protocol", "semantic_contract": 'chain-of-thought' + ".method.v2", "entrypoint": METHOD_ENTRYPOINT}

__all__ = tuple(dict.fromkeys((*__all__, 'METHOD_SPEC')))
