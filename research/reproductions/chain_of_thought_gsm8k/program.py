from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import CHAIN_OF_THOUGHT_GSM8K_FIDELITY

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


def _reasoner_view(request: MethodNodeRequest) -> JsonObject:
    f = CHAIN_OF_THOUGHT_GSM8K_FIDELITY
    question = request.state.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("CoT method state requires question")
    return {
        "task_id": request.state.get("task_id"),
        "question": question,
        "prompt_mode": f.prompt_mode,
        "prompt_bundle": "cot.gsm8k.neurips2022.appendix-table20",
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


def _record_completion(request: MethodNodeRequest) -> MethodNodeResult:
    text = _completion(request.previous_value)
    return MethodNodeResult(
        value={"completion": text},
        state_update={"completion": text},
        next_node="return",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    completion = request.state.get("completion")
    if not isinstance(completion, str) or not completion.strip():
        raise ValueError("CoT completion is missing")
    return MethodNodeResult(
        value={
            "task_id": request.state.get("task_id"),
            "completion": completion,
            "reasoning_path_count": 1,
        }
    )


def build_chain_of_thought_gsm8k_method_program() -> MethodProgram:
    f = CHAIN_OF_THOUGHT_GSM8K_FIDELITY
    configuration: JsonObject = {
        "publication_lane_digest": f.publication.lane_digest,
        "benchmark_id": f.benchmark_id,
        "benchmark_split": f.benchmark_split,
        "exemplar_count": f.exemplar_count,
        "exemplar_source": f.exemplar_source,
        "prompt_mode": f.prompt_mode,
        "decoding": f.decoding,
        "samples_per_task": f.samples_per_task,
        "calculator_enabled": f.calculator_enabled,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="chain-of-thought",
            implementation_version="neurips-2022-final",
            abi_version="noetrium.method-machine.v1",
            schema_version="chain-of-thought.gsm8k.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="reason")
    builder.agent(
        "reason",
        "cot.gsm8k.reason",
        _REASONER,
        ("record",),
        view_handler=_reasoner_view,
    )
    builder.compute(
        "record",
        "cot.gsm8k.record-completion",
        _record_completion,
        ("return",),
    )
    builder.return_node("return", "cot.gsm8k.result", _return_result)
    return builder.build(
        configuration=configuration,
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=("cot.reasoning-completion", "model.invocation"),
        metric_names=("task_success", "model_call_count"),
        artifact_kinds=("cot_completion",),
    )


CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM = build_chain_of_thought_gsm8k_method_program()

__all__ = [
    "CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM",
    "build_chain_of_thought_gsm8k_method_program",
    "chain_of_thought_gsm8k_initial_state",
]
