from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
import re

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

from .fidelity import SELF_CONSISTENCY_GSM8K_FIDELITY

_REASONER = "self-consistency.reasoner"
_ANSWER_PHRASE = re.compile(
    r"(?i)(?:the\s+answer\s+is|answer\s*:)\s*\$?([-+]?\d[\d,]*(?:\.\d+)?)"
)
_NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def self_consistency_gsm8k_initial_state(*, task_id: str, question: str) -> JsonObject:
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("Self-Consistency task_id is required")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Self-Consistency GSM8K question is required")
    return {
        "task_id": task_id,
        "question": question,
        "sample_index": 0,
        "samples": (),
        "selected_answer": "",
        "selected_vote_count": 0,
    }


def _reasoner_view(request: MethodNodeRequest) -> JsonObject:
    f = SELF_CONSISTENCY_GSM8K_FIDELITY
    question = request.state.get("question")
    sample_index = request.state.get("sample_index")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Self-Consistency state requires question")
    if type(sample_index) is not int or sample_index < 0:
        raise ValueError("Self-Consistency sample_index is invalid")
    return {
        "task_id": request.state.get("task_id"),
        "question": question,
        "sample_index": sample_index,
        "sample_count": f.reasoning_path_count,
        "prompt_bundle": "cot.gsm8k.neurips2022.appendix-table20",
        "cot_exemplar_count": f.cot_exemplar_count,
        "sampling": {
            "strategy": "temperature_top_k",
            "temperature": f.temperature,
            "top_k": f.top_k,
        },
    }


def _completion(value: JsonValue) -> str:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, Mapping):
        row = value.get("completion", value.get("text"))
        if isinstance(row, str) and row.strip():
            return row
    raise TypeError("Self-Consistency sample must contain completion text")


def extract_gsm8k_sample_answer(completion: str) -> str:
    """Task-specific final-answer projection used before self-consistency voting."""

    if not isinstance(completion, str) or not completion.strip():
        raise ValueError("Self-Consistency completion must be non-empty")
    matches = _ANSWER_PHRASE.findall(completion)
    raw = matches[-1] if matches else (_NUMBER.findall(completion)[-1] if _NUMBER.findall(completion) else None)
    if raw is None:
        raise ValueError("Self-Consistency completion contains no numeric final answer")
    normalized = raw.replace(",", "")
    try:
        number = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("Self-Consistency final answer is not numeric") from exc
    if number == number.to_integral():
        return str(number.quantize(Decimal("1")))
    return format(number.normalize(), "f")


def _record_sample(request: MethodNodeRequest) -> MethodNodeResult:
    f = SELF_CONSISTENCY_GSM8K_FIDELITY
    completion = _completion(request.previous_value)
    answer = extract_gsm8k_sample_answer(completion)
    samples = (
        *(
            freeze_json(row)
            for row in request.state.get("samples", ())
            if isinstance(row, Mapping)
        ),
        {"completion": completion, "answer": answer},
    )
    sample_index = request.state.get("sample_index")
    if type(sample_index) is not int:
        raise TypeError("Self-Consistency sample_index must be integer")
    next_index = sample_index + 1
    return MethodNodeResult(
        value={"sample_index": sample_index, "answer": answer},
        state_update={
            "sample_index": next_index,
            "samples": samples,
        },
        next_node=(
            "aggregate"
            if next_index >= f.reasoning_path_count
            else "sample"
        ),
    )


def _aggregate(request: MethodNodeRequest) -> MethodNodeResult:
    raw = request.state.get("samples")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise TypeError("Self-Consistency samples must be a sequence")
    rows = tuple(row for row in raw if isinstance(row, Mapping))
    if len(rows) != SELF_CONSISTENCY_GSM8K_FIDELITY.reasoning_path_count:
        raise ValueError("Self-Consistency requires exactly 40 sampled reasoning paths")

    counts: dict[str, int] = {}
    first_index: dict[str, int] = {}
    for index, row in enumerate(rows):
        answer = row.get("answer")
        if not isinstance(answer, str) or not answer:
            raise ValueError("Self-Consistency sample is missing normalized answer")
        counts[answer] = counts.get(answer, 0) + 1
        first_index.setdefault(answer, index)

    selected = max(
        counts,
        key=lambda answer: (counts[answer], -first_index[answer]),
    )
    return MethodNodeResult(
        value={
            "selected_answer": selected,
            "vote_count": counts[selected],
            "answer_histogram": tuple(sorted(counts.items())),
        },
        state_update={
            "selected_answer": selected,
            "selected_vote_count": counts[selected],
        },
        next_node="return",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    answer = request.state.get("selected_answer")
    votes = request.state.get("selected_vote_count")
    if not isinstance(answer, str) or not answer:
        raise ValueError("Self-Consistency selected answer is missing")
    if type(votes) is not int or votes <= 0:
        raise ValueError("Self-Consistency selected vote count is invalid")
    return MethodNodeResult(
        value={
            "task_id": request.state.get("task_id"),
            "selected_answer": answer,
            "selected_vote_count": votes,
            "reasoning_path_count": SELF_CONSISTENCY_GSM8K_FIDELITY.reasoning_path_count,
            "samples": request.state.get("samples", ()),
        }
    )


def build_self_consistency_gsm8k_method_program() -> MethodProgram:
    f = SELF_CONSISTENCY_GSM8K_FIDELITY
    configuration: JsonObject = {
        "publication_lane_digest": f.publication.lane_digest,
        "benchmark_id": f.benchmark_id,
        "cot_exemplar_count": f.cot_exemplar_count,
        "cot_prompt_source": f.cot_prompt_source,
        "reasoning_path_count": f.reasoning_path_count,
        "temperature": f.temperature,
        "top_k": f.top_k,
        "aggregation": f.aggregation,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="self-consistency",
            implementation_version="iclr-2023-final",
            abi_version="noetrium.method-machine.v1",
            schema_version="self-consistency.gsm8k.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="sample")
    builder.agent(
        "sample",
        "self-consistency.gsm8k.sample",
        _REASONER,
        ("record_sample",),
        view_handler=_reasoner_view,
        max_visits=f.reasoning_path_count,
    )
    builder.route(
        "record_sample",
        "self-consistency.gsm8k.record-sample",
        _record_sample,
        ("sample", "aggregate"),
        max_visits=f.reasoning_path_count,
    )
    builder.compute(
        "aggregate",
        "self-consistency.gsm8k.marginalize",
        _aggregate,
        ("return",),
    )
    builder.return_node("return", "self-consistency.gsm8k.result", _return_result)
    return builder.build(
        configuration=configuration,
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "self-consistency.reasoning-paths",
            "self-consistency.answer-histogram",
            "model.invocation",
        ),
        metric_names=(
            "task_success",
            "model_call_count",
            "selected_vote_count",
        ),
        artifact_kinds=("self_consistency_samples",),
    )


SELF_CONSISTENCY_GSM8K_METHOD_PROGRAM = build_self_consistency_gsm8k_method_program()

__all__ = [
    "SELF_CONSISTENCY_GSM8K_METHOD_PROGRAM",
    "build_self_consistency_gsm8k_method_program",
    "extract_gsm8k_sample_answer",
    "self_consistency_gsm8k_initial_state",
]
