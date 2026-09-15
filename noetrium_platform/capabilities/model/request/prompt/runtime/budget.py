from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Protocol

from .blocks import PromptBlock
from .runtime import ActivePromptBundle


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class ConservativeCharTokenCounter:
    """Deterministic fallback estimate; deployments may inject a frozen tokenizer."""

    def __init__(self, chars_per_token: float = 2.5) -> None:
        if not math.isfinite(chars_per_token) or chars_per_token <= 0:
            raise ValueError("chars_per_token must be finite and positive")
        self.chars_per_token = float(chars_per_token)

    def count(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("token counter input must be text")
        return max(1, math.ceil(len(text) / self.chars_per_token))


@dataclass(frozen=True, slots=True)
class ModelRequestBudgetReport:
    """Pre-transport split input/output budget for one model request."""

    context_length: int
    requested_output_tokens: int
    input_tokens: int
    safety_tokens: int
    counter_kind: str

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.requested_output_tokens + self.safety_tokens

    @property
    def available_input_tokens(self) -> int:
        return self.context_length - self.requested_output_tokens - self.safety_tokens

    @property
    def available_output_tokens(self) -> int:
        return max(0, self.context_length - self.input_tokens - self.safety_tokens)

    @property
    def fits(self) -> bool:
        return self.total_tokens <= self.context_length


class ModelRequestBudgetExceeded(ValueError):
    def __init__(self, report: ModelRequestBudgetReport) -> None:
        self.report = report
        super().__init__(
            "model request exceeds context budget: "
            f"input={report.input_tokens}, output={report.requested_output_tokens}, "
            f"safety={report.safety_tokens}, context={report.context_length}"
        )


def _collect_text(value: object, output: list[str]) -> None:
    if isinstance(value, str):
        output.append(value)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if key != "model":
                _collect_text(item, output)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _collect_text(item, output)


def check_model_request_budget(
    body: Mapping[str, object],
    *,
    context_length: int,
    compiled_prompt_text: str | None = None,
    token_counter: TokenCounter | None = None,
    safety_tokens: int = 0,
) -> ModelRequestBudgetReport | None:
    """Validate input plus reserved output before recording or transport."""

    if type(context_length) is not int or context_length <= 0:
        raise ValueError("model context_length must be a positive integer")
    if type(safety_tokens) is not int or safety_tokens < 0:
        raise ValueError("model budget safety_tokens must be non-negative")
    if "max_tokens" not in body:
        return None
    output_tokens = body["max_tokens"]
    if type(output_tokens) is not int or output_tokens < 0:
        raise ValueError("model request max_tokens must be a non-negative integer")
    if compiled_prompt_text is not None and not isinstance(compiled_prompt_text, str):
        raise TypeError("compiled_prompt_text must be text when provided")

    parts: list[str] = []
    if "messages" in body:
        _collect_text(body, parts)
    elif compiled_prompt_text is not None:
        _collect_text(compiled_prompt_text, parts)
        _collect_text(body, parts)
    else:
        _collect_text(body, parts)
    counter = token_counter or ConservativeCharTokenCounter()
    input_tokens = counter.count("\n".join(parts))
    if type(input_tokens) is not int or input_tokens < 0:
        raise TypeError("model token counter must return a non-negative integer")
    report = ModelRequestBudgetReport(
        context_length=context_length,
        requested_output_tokens=output_tokens,
        input_tokens=input_tokens,
        safety_tokens=safety_tokens,
        counter_kind="exact" if token_counter is not None else "deterministic_estimate",
    )
    if not report.fits:
        raise ModelRequestBudgetExceeded(report)
    return report


def fit_model_request_budget(
    body: Mapping[str, object],
    *,
    context_length: int,
    compiled_prompt_text: str | None = None,
    token_counter: TokenCounter | None = None,
    safety_tokens: int = 0,
    minimum_output_tokens: int = 1,
) -> tuple[Mapping[str, object], ModelRequestBudgetReport | None]:
    """Cap only output reservation; never discard or rewrite input context."""

    if type(minimum_output_tokens) is not int or minimum_output_tokens < 0:
        raise ValueError("minimum_output_tokens must be a non-negative integer")
    if "max_tokens" not in body:
        return body, None
    try:
        initial = check_model_request_budget(
            body,
            context_length=context_length,
            compiled_prompt_text=compiled_prompt_text,
            token_counter=token_counter,
            safety_tokens=safety_tokens,
        )
    except ModelRequestBudgetExceeded as exc:
        initial = exc.report
    if initial is not None and initial.fits:
        return body, initial
    if initial is None or initial.available_output_tokens < minimum_output_tokens:
        if initial is not None:
            raise ModelRequestBudgetExceeded(initial)
        raise ValueError("model request has no output budget")

    fitted = dict(body)
    fitted["max_tokens"] = min(int(body["max_tokens"]), initial.available_output_tokens)
    report = check_model_request_budget(
        fitted,
        context_length=context_length,
        compiled_prompt_text=compiled_prompt_text,
        token_counter=token_counter,
        safety_tokens=safety_tokens,
    )
    return fitted, report


@dataclass(frozen=True, slots=True)
class PromptBudgetReport:
    context_length: int
    reserved_output_tokens: int
    safety_tokens: int
    static_tokens: int
    dynamic_tokens: tuple[tuple[str, int], ...]
    total_input_tokens: int
    available_input_tokens: int

    @property
    def fits(self) -> bool:
        return self.total_input_tokens <= self.available_input_tokens


class PromptBudgetExceeded(ValueError):
    def __init__(self, report: PromptBudgetReport) -> None:
        super().__init__(
            "prompt budget exceeded: "
            f"input={report.total_input_tokens} available={report.available_input_tokens}; "
            "no truncation performed"
        )
        self.report = report


class PromptBudgetPlanner:
    """Measure prompt blocks; never mutate context or change the selected model."""

    def __init__(self, counter: TokenCounter | None = None, safety_tokens: int = 1024) -> None:
        if type(safety_tokens) is not int or safety_tokens < 0:
            raise ValueError("prompt budget safety_tokens must be non-negative")
        self.counter = counter or ConservativeCharTokenCounter()
        self.safety_tokens = safety_tokens

    def check(
        self,
        bundle: ActivePromptBundle,
        blocks: tuple[PromptBlock, ...],
        *,
        context_length: int,
    ) -> PromptBudgetReport:
        if type(context_length) is not int or context_length <= 0:
            raise ValueError("prompt context_length must be a positive integer")
        static_tokens = self.counter.count(bundle.text)
        dynamic_tokens = tuple(
            (block.kind.value, self.counter.count(block.content)) for block in blocks
        )
        available = context_length - bundle.max_output_tokens - self.safety_tokens
        report = PromptBudgetReport(
            context_length=context_length,
            reserved_output_tokens=bundle.max_output_tokens,
            safety_tokens=self.safety_tokens,
            static_tokens=static_tokens,
            dynamic_tokens=dynamic_tokens,
            total_input_tokens=static_tokens + sum(value for _, value in dynamic_tokens),
            available_input_tokens=available,
        )
        if available <= 0 or not report.fits:
            raise PromptBudgetExceeded(report)
        return report
