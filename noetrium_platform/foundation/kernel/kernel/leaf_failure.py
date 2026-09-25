from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .errors import describe_exception


class LeafFailureClass(StrEnum):
    BUSINESS = "business"
    EXTERNAL_EFFECT_UNCERTAIN = "external_effect_uncertain"
    PERSISTENCE = "persistence"
    DIAGNOSTIC = "diagnostic"
    PROGRAMMING = "programming"


@dataclass(frozen=True, slots=True)
class LeafFailureReceipt:
    code: str
    classification: LeafFailureClass
    retryable: bool
    effect_certainty: str
    cause_type: str
    detail: str
    contract_digest: str | None = None


def receipt(exc: BaseException, *, code: str, classification: LeafFailureClass, retryable: bool, effect_certainty: str, contract_digest: str | None = None) -> LeafFailureReceipt:
    descriptor = describe_exception(exc)
    return LeafFailureReceipt(code, classification, retryable, effect_certainty, descriptor.qualified_type, descriptor.safe_message, contract_digest)


__all__ = ["LeafFailureClass", "LeafFailureReceipt", "receipt"]
