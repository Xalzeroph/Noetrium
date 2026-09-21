from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re


_ANSWER_PHRASE = re.compile(
    r"(?i)(?:the\s+answer\s+is|answer\s*:?)\s*"
    r"(-?\$?[0-9][0-9,]*(?:\.[0-9]+)?)"
)
_NUMBER = re.compile(r"-?\$?[0-9][0-9,]*(?:\.[0-9]+)?")


def normalize_gsm8k_numeric_answer(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("GSM8K numeric answer must be non-empty")
    normalized = value.strip().replace("$", "").replace(",", "")
    try:
        number = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("GSM8K answer is not numeric") from exc
    if not number.is_finite():
        raise ValueError("GSM8K answer must be finite")
    if number == number.to_integral():
        return str(number.quantize(Decimal("1")))
    return format(number.normalize(), "f")


def extract_gsm8k_completion_answer(completion: str) -> str:
    """Project model text to the benchmark's final numeric answer."""

    if not isinstance(completion, str) or not completion.strip():
        raise ValueError("GSM8K completion must be non-empty")
    phrase_matches = _ANSWER_PHRASE.findall(completion)
    if phrase_matches:
        raw = phrase_matches[-1]
    else:
        numeric_matches = _NUMBER.findall(completion)
        if not numeric_matches:
            raise ValueError("GSM8K completion contains no numeric final answer")
        raw = numeric_matches[-1]
    return normalize_gsm8k_numeric_answer(raw)


def verify_gsm8k_completion(completion: str, gold_final_answer: str) -> tuple[bool, str]:
    predicted = extract_gsm8k_completion_answer(completion)
    gold = normalize_gsm8k_numeric_answer(gold_final_answer)
    return predicted == gold, predicted


__all__ = [
    "extract_gsm8k_completion_answer",
    "normalize_gsm8k_numeric_answer",
    "verify_gsm8k_completion",
]
