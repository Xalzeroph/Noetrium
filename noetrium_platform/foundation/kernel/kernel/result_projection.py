from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from .canonical import canonical_digest
from .operation import EffectReceipt, OperationAuxiliaryFailure

R = TypeVar("R")


@dataclass(frozen=True, slots=True)
class ProjectedOperationResult(Generic[R]):
    output: R
    output_digest: str | None
    effect_receipts: tuple[EffectReceipt, ...]
    diagnostics: dict[str, object]
    auxiliary_failures: tuple[OperationAuxiliaryFailure, ...]


class OperationResultProjector:
    """Best-effort deterministic projection after successful component execution.

    Projection cannot turn a successful component call into a failed operation. Any
    projection problem is reported only as an auxiliary failure.
    """

    def project(
        self,
        output: R,
        *,
        digest_output: bool,
        effect_projector: Callable[[R], tuple[EffectReceipt, ...]] | None,
    ) -> ProjectedOperationResult[R]:
        diagnostics: dict[str, object] = {}
        auxiliary: list[OperationAuxiliaryFailure] = []
        output_digest: str | None = None
        if digest_output:
            try:
                output_digest = canonical_digest(output)
            except Exception as exc:
                diagnostics["post_execution"] = True
                auxiliary.append(OperationAuxiliaryFailure.from_exception(
                    "kernel.output_digest",
                    "post_execution",
                    exc,
                ))

        effects: tuple[EffectReceipt, ...] = ()
        if effect_projector is not None:
            try:
                effects = tuple(effect_projector(output))
            except Exception as exc:
                diagnostics["post_execution"] = True
                auxiliary.append(OperationAuxiliaryFailure.from_exception(
                    "kernel.effect_projector",
                    "post_execution",
                    exc,
                ))

        return ProjectedOperationResult(
            output=output,
            output_digest=output_digest,
            effect_receipts=effects,
            diagnostics=diagnostics,
            auxiliary_failures=tuple(auxiliary),
        )


__all__ = ["OperationResultProjector", "ProjectedOperationResult"]
