from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .contracts import ModelRevisionIdentity, ModelUpdateProposal


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def _sha256(value: object, field: str) -> str:
    digest = _text(value, field)
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return digest


@dataclass(frozen=True, slots=True)
class ModelUpdateSource:
    source_id: str
    role: str
    revision_digest: str

    def __post_init__(self) -> None:
        _text(self.source_id, "model update source id")
        _text(self.role, "model update source role")
        _sha256(self.revision_digest, "model update source revision digest")
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ModelUpdatePlan:
    plan_id: str
    predecessor_revision_digest: str
    update_contract_id: str
    implementation_digest: str
    configuration_digest: str
    training_input_digest: str
    randomness_digest: str | None = None
    source_revisions: tuple[ModelUpdateSource, ...] = ()
    output_lineage_contract_id: str = "model-revision.v2"

    def __post_init__(self) -> None:
        _text(self.plan_id, "model update plan id")
        predecessor = _sha256(
            self.predecessor_revision_digest, "model update plan predecessor digest"
        )
        _text(self.update_contract_id, "model update plan contract id")
        _sha256(self.implementation_digest, "model update plan implementation digest")
        _sha256(self.configuration_digest, "model update plan configuration digest")
        _sha256(self.training_input_digest, "model update plan training input digest")
        if self.randomness_digest is not None:
            _sha256(self.randomness_digest, "model update plan randomness digest")
        _text(self.output_lineage_contract_id, "model update plan output lineage contract id")
        if not isinstance(self.source_revisions, tuple):
            raise TypeError("model update plan sources must be a tuple")
        if any(not isinstance(source, ModelUpdateSource) for source in self.source_revisions):
            raise TypeError("model update plan sources must contain ModelUpdateSource values")
        sources = tuple(sorted(self.source_revisions, key=lambda source: source.source_id))
        if len({source.source_id for source in sources}) != len(sources):
            raise ValueError("model update plan source ids must be unique")
        if any(source.revision_digest == predecessor for source in sources):
            raise ValueError("model update plan sources must not duplicate the predecessor revision")
        object.__setattr__(self, "source_revisions", sources)

    def digest(self) -> str:
        return canonical_digest(self)

    def to_proposal(
        self,
        proposal_id: str,
        *,
        evidence_refs: tuple[str, ...] = (),
    ) -> ModelUpdateProposal:
        return ModelUpdateProposal(
            proposal_id=proposal_id,
            predecessor_revision_digest=self.predecessor_revision_digest,
            update_contract_id=self.update_contract_id,
            implementation_digest=self.implementation_digest,
            configuration_digest=self.configuration_digest,
            training_input_digest=self.training_input_digest,
            randomness_digest=self.randomness_digest,
            evidence_refs=evidence_refs,
        )

    def require_proposal(self, proposal: ModelUpdateProposal) -> None:
        if not isinstance(proposal, ModelUpdateProposal):
            raise TypeError("model update plan requires ModelUpdateProposal")
        expected = (
            self.predecessor_revision_digest,
            self.update_contract_id,
            self.implementation_digest,
            self.configuration_digest,
            self.training_input_digest,
            self.randomness_digest,
        )
        actual = (
            proposal.predecessor_revision_digest,
            proposal.update_contract_id,
            proposal.implementation_digest,
            proposal.configuration_digest,
            proposal.training_input_digest,
            proposal.randomness_digest,
        )
        if actual != expected:
            raise ValueError("model update proposal does not match the exact update plan")


@dataclass(frozen=True, slots=True)
class ModelUpdateBuildEvidence:
    plan_digest: str
    candidate_revision_digest: str
    evidence_digest: str
    producer_contract_id: str

    def __post_init__(self) -> None:
        _sha256(self.plan_digest, "model update build evidence plan digest")
        _sha256(self.candidate_revision_digest, "model update build evidence candidate digest")
        _sha256(self.evidence_digest, "model update build evidence digest")
        _text(self.producer_contract_id, "model update build evidence producer contract id")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ModelUpdateBuildReceipt:
    plan: ModelUpdatePlan
    proposal: ModelUpdateProposal
    predecessor: ModelRevisionIdentity
    candidate: ModelRevisionIdentity
    producer_contract_id: str
    producer_implementation_digest: str
    build_evidence: tuple[ModelUpdateBuildEvidence, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.plan, ModelUpdatePlan):
            raise TypeError("model update build receipt plan must be typed")
        if not isinstance(self.proposal, ModelUpdateProposal):
            raise TypeError("model update build receipt proposal must be typed")
        if not isinstance(self.predecessor, ModelRevisionIdentity):
            raise TypeError("model update build receipt predecessor must be typed")
        if not isinstance(self.candidate, ModelRevisionIdentity):
            raise TypeError("model update build receipt candidate must be typed")
        self.plan.require_proposal(self.proposal)
        predecessor_digest = self.predecessor.digest()
        if self.plan.predecessor_revision_digest != predecessor_digest:
            raise ValueError("model update build plan does not bind exact predecessor")
        if self.candidate.parent_revision_digest != predecessor_digest:
            raise ValueError("model update build candidate does not bind exact predecessor")
        if self.candidate.model.logical_name != self.predecessor.model.logical_name:
            raise ValueError("model update build must preserve logical model identity")
        if self.candidate.model.model_id != self.predecessor.model.model_id:
            raise ValueError("model update build must preserve model_id identity")
        if self.candidate.lineage_contract_id != self.plan.output_lineage_contract_id:
            raise ValueError("model update build candidate lineage contract does not match plan")
        if self.candidate.digest() == predecessor_digest:
            raise ValueError("model update build candidate must be a distinct revision")
        _text(self.producer_contract_id, "model update build producer contract id")
        _sha256(
            self.producer_implementation_digest,
            "model update build producer implementation digest",
        )
        if not isinstance(self.build_evidence, tuple) or not self.build_evidence:
            raise TypeError("model update build evidence must be a non-empty tuple")
        if any(not isinstance(row, ModelUpdateBuildEvidence) for row in self.build_evidence):
            raise TypeError("model update build evidence must be typed")
        plan_digest = self.plan.digest()
        candidate_digest = self.candidate.digest()
        for row in self.build_evidence:
            if row.plan_digest != plan_digest or row.candidate_revision_digest != candidate_digest:
                raise ValueError("model update build evidence must bind exact plan and candidate")
        digests = tuple(row.digest() for row in self.build_evidence)
        if len(set(digests)) != len(digests):
            raise ValueError("model update build evidence must be unique")

    def digest(self) -> str:
        return canonical_digest(self)


@runtime_checkable
class ModelUpdateProducerPort(Protocol):
    @property
    def producer_contract_id(self) -> str: ...

    @property
    def implementation_digest(self) -> str: ...

    def build_candidate(
        self,
        plan: ModelUpdatePlan,
        proposal: ModelUpdateProposal,
        predecessor: ModelRevisionIdentity,
    ) -> ModelUpdateBuildReceipt: ...


__all__ = [
    "ModelUpdateBuildEvidence",
    "ModelUpdateBuildReceipt",
    "ModelUpdatePlan",
    "ModelUpdateProducerPort",
    "ModelUpdateSource",
]
