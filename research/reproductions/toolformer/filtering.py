from __future__ import annotations

import math
from dataclasses import dataclass

from .fidelity import TOOLFORMER_FIDELITY


def toolformer_raw_future_weight(offset: int) -> float:
    """Paper raw weight: max(0, 1 - 0.2 * t)."""
    if type(offset) is not int or offset < 0:
        raise ValueError("Toolformer future-token offset must be non-negative")
    return max(
        0.0,
        1.0 - TOOLFORMER_FIDELITY.future_loss_raw_decay * offset,
    )


def toolformer_normalized_future_weights(length: int) -> tuple[float, ...]:
    if type(length) is not int or length <= 0:
        raise ValueError("Toolformer future-token window length must be positive")
    raw = tuple(toolformer_raw_future_weight(offset) for offset in range(length))
    total = sum(raw)
    if total <= 0.0:
        raise ValueError("Toolformer future-token weights must have positive mass")
    return tuple(value / total for value in raw)


@dataclass(frozen=True, slots=True)
class ToolformerCallLosses:
    """Loss terms from Section 2 of the paper.

    no_call is L_i(epsilon); call_without_result is L_i(e(c_i, epsilon));
    call_with_result is L_i(e(c_i, r_i)).
    """

    no_call: float
    call_without_result: float
    call_with_result: float

    def __post_init__(self) -> None:
        for field_name in (
            "no_call",
            "call_without_result",
            "call_with_result",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"Toolformer {field_name} loss must be numeric")
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"Toolformer {field_name} loss must be finite non-negative")

    @property
    def loss_without_result(self) -> float:
        return min(float(self.no_call), float(self.call_without_result))

    @property
    def utility(self) -> float:
        return self.loss_without_result - float(self.call_with_result)


def toolformer_keep_call(
    losses: ToolformerCallLosses,
    *,
    filtering_threshold: float,
) -> bool:
    if not isinstance(losses, ToolformerCallLosses):
        raise TypeError("Toolformer filtering requires ToolformerCallLosses")
    if (
        isinstance(filtering_threshold, bool)
        or not isinstance(filtering_threshold, (int, float))
        or not math.isfinite(float(filtering_threshold))
        or float(filtering_threshold) < 0.0
    ):
        raise ValueError("Toolformer filtering threshold must be finite non-negative")
    return losses.utility >= float(filtering_threshold)


__all__ = [
    "ToolformerCallLosses",
    "toolformer_keep_call",
    "toolformer_normalized_future_weights",
    "toolformer_raw_future_weight",
]
