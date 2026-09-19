from __future__ import annotations

from collections.abc import Callable

from noetrium_platform.capabilities.model.catalog.revision.api import (
    ModelRevisionIdentity,
    ModelUpdateBuildEvidence,
    ModelUpdateBuildReceipt,
    ModelUpdatePlan,
    ModelUpdateProposal,
)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def _sha256(value: object, field: str) -> str:
    digest = _text(value, field)
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return digest


BuildHandler = Callable[
    [ModelUpdatePlan, ModelRevisionIdentity],
    tuple[ModelRevisionIdentity, tuple[str, ...]],
]


class FunctionalModelUpdateProducer:
    """Typed adapter for one update/training implementation; owns no revision state."""

    def __init__(
        self,
        *,
        producer_contract_id: str,
        implementation_digest: str,
        handler: BuildHandler,
    ) -> None:
        self._producer_contract_id = _text(
            producer_contract_id, "model update producer contract id"
        )
        self._implementation_digest = _sha256(
            implementation_digest, "model update producer implementation digest"
        )
        if not callable(handler):
            raise TypeError("model update producer handler must be callable")
        self._handler = handler

    @property
    def producer_contract_id(self) -> str:
        return self._producer_contract_id

    @property
    def implementation_digest(self) -> str:
        return self._implementation_digest

    def build_candidate(
        self,
        plan: ModelUpdatePlan,
        proposal: ModelUpdateProposal,
        predecessor: ModelRevisionIdentity,
    ) -> ModelUpdateBuildReceipt:
        if not isinstance(plan, ModelUpdatePlan):
            raise TypeError("model update producer plan must be typed")
        if not isinstance(proposal, ModelUpdateProposal):
            raise TypeError("model update producer proposal must be typed")
        if not isinstance(predecessor, ModelRevisionIdentity):
            raise TypeError("model update producer predecessor must be typed")
        plan.require_proposal(proposal)
        if plan.predecessor_revision_digest != predecessor.digest():
            raise ValueError("model update producer plan does not bind exact predecessor")
        candidate, evidence_digests = self._handler(plan, predecessor)
        if not isinstance(candidate, ModelRevisionIdentity):
            raise TypeError("model update producer handler must return ModelRevisionIdentity")
        if not isinstance(evidence_digests, tuple) or not evidence_digests:
            raise TypeError("model update producer evidence digests must be a non-empty tuple")
        evidence = tuple(
            ModelUpdateBuildEvidence(
                plan_digest=plan.digest(),
                candidate_revision_digest=candidate.digest(),
                evidence_digest=_sha256(digest, "model update producer evidence digest"),
                producer_contract_id=self._producer_contract_id,
            )
            for digest in evidence_digests
        )
        return ModelUpdateBuildReceipt(
            plan=plan,
            proposal=proposal,
            predecessor=predecessor,
            candidate=candidate,
            producer_contract_id=self._producer_contract_id,
            producer_implementation_digest=self._implementation_digest,
            build_evidence=evidence,
        )


__all__ = ["BuildHandler", "FunctionalModelUpdateProducer"]
