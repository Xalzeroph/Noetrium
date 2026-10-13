from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity, canonical_digest

if TYPE_CHECKING:
    from .update import ModelUpdateBuildReceipt


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def _sha256(value: object, field: str) -> str:
    digest = _text(value, field)
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return digest


def _generation(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _model_identity(value: ImmutableModelIdentity) -> None:
    if not isinstance(value, ImmutableModelIdentity):
        raise TypeError("model revision identity must carry ImmutableModelIdentity")
    for field in ("logical_name", "model_id", "revision", "engine", "engine_version", "dtype"):
        _text(getattr(value, field), f"model identity {field}")
    if value.quantization is not None:
        _text(value.quantization, "model identity quantization")
    if value.tokenizer_revision is not None:
        _text(value.tokenizer_revision, "model identity tokenizer revision")
    if type(value.context_length) is not int or value.context_length <= 0:
        raise ValueError("model identity context_length must be positive")


class ModelRevisionConflictError(RuntimeError):
    """The caller observed a stale durable revision generation or active revision."""


class ModelRevisionIntegrityError(RuntimeError):
    """Durable revision state is corrupt, torn, or semantically inconsistent."""


class ModelRevisionStateError(RuntimeError):
    """The requested revision transition is illegal in the current durable state."""


@dataclass(frozen=True, slots=True)
class ModelRevisionIdentity:
    model: ImmutableModelIdentity
    revision_artifact_digest: str
    parent_revision_digest: str | None = None
    lineage_contract_id: str = "model-revision.v2"

    def __post_init__(self) -> None:
        _model_identity(self.model)
        _sha256(self.revision_artifact_digest, "model revision artifact digest")
        _text(self.lineage_contract_id, "model revision lineage contract id")
        if self.parent_revision_digest is not None:
            _sha256(self.parent_revision_digest, "model revision parent digest")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ModelUpdateProposal:
    proposal_id: str
    predecessor_revision_digest: str
    update_contract_id: str
    implementation_digest: str
    configuration_digest: str
    training_input_digest: str
    randomness_digest: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.proposal_id, "model update proposal id")
        _sha256(self.predecessor_revision_digest, "model update predecessor digest")
        _text(self.update_contract_id, "model update contract id")
        _sha256(self.implementation_digest, "model update implementation digest")
        _sha256(self.configuration_digest, "model update configuration digest")
        _sha256(self.training_input_digest, "model update training input digest")
        if self.randomness_digest is not None:
            _sha256(self.randomness_digest, "model update randomness digest")
        if not isinstance(self.evidence_refs, tuple):
            raise TypeError("model update evidence refs must be a tuple")
        for ref in self.evidence_refs:
            _text(ref, "model update evidence ref")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("model update evidence refs must be unique")

    def digest(self) -> str:
        return canonical_digest(self)


class ModelRevisionEvidenceKind(StrEnum):
    VALIDATION = "validation"
    QUALIFICATION = "qualification"
    EVALUATION = "evaluation"
    ROLLBACK_TRIGGER = "rollback-trigger"


@dataclass(frozen=True, slots=True)
class ModelRevisionEvidence:
    kind: ModelRevisionEvidenceKind
    revision_digest: str
    evidence_digest: str
    producer_contract_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ModelRevisionEvidenceKind):
            raise TypeError("model revision evidence kind must be typed")
        _sha256(self.revision_digest, "model revision evidence revision digest")
        _sha256(self.evidence_digest, "model revision evidence digest")
        _text(self.producer_contract_id, "model revision evidence producer contract id")

    def digest(self) -> str:
        return canonical_digest(self)


def _evidence(
    values: object,
    *,
    field: str,
    kind: ModelRevisionEvidenceKind,
    revision_digest: str,
) -> tuple[ModelRevisionEvidence, ...]:
    if not isinstance(values, tuple) or not values:
        raise TypeError(f"{field} must be a non-empty tuple")
    if any(not isinstance(value, ModelRevisionEvidence) for value in values):
        raise TypeError(f"{field} must contain typed model revision evidence")
    typed = values
    for value in typed:
        if value.kind is not kind:
            raise ValueError(f"{field} contains wrong evidence kind")
        if value.revision_digest != revision_digest:
            raise ValueError(f"{field} must bind the exact model revision")
    digests = tuple(value.digest() for value in typed)
    if len(set(digests)) != len(digests):
        raise ValueError(f"{field} must not contain duplicate evidence")
    return typed


@dataclass(frozen=True, slots=True)
class PreparedModelRevision:
    proposal: ModelUpdateProposal
    predecessor: ModelRevisionIdentity
    candidate: ModelRevisionIdentity
    build_receipt_digest: str
    preparation_generation: int
    recovery_anchor_digest: str
    validation_plan_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, ModelUpdateProposal):
            raise TypeError("prepared model revision must carry ModelUpdateProposal")
        if not isinstance(self.predecessor, ModelRevisionIdentity):
            raise TypeError("prepared model predecessor must be ModelRevisionIdentity")
        if not isinstance(self.candidate, ModelRevisionIdentity):
            raise TypeError("prepared model candidate must be ModelRevisionIdentity")
        predecessor_digest = self.predecessor.digest()
        if self.proposal.predecessor_revision_digest != predecessor_digest:
            raise ValueError("model update proposal does not bind the exact predecessor")
        if self.candidate.parent_revision_digest != predecessor_digest:
            raise ValueError("prepared model candidate must bind the exact predecessor revision")
        if self.candidate.model.logical_name != self.predecessor.model.logical_name:
            raise ValueError("model revision candidate must preserve logical model identity")
        if self.candidate.model.model_id != self.predecessor.model.model_id:
            raise ValueError("model revision candidate must preserve model_id identity")
        if self.candidate.digest() == predecessor_digest:
            raise ValueError("prepared model candidate must be a distinct revision")
        _sha256(self.build_receipt_digest, "prepared model build receipt digest")
        _generation(self.preparation_generation, "prepared model generation")
        _sha256(self.recovery_anchor_digest, "prepared model recovery anchor digest")
        _sha256(self.validation_plan_digest, "prepared model validation plan digest")

    @property
    def proposal_digest(self) -> str:
        return self.proposal.digest()

    @property
    def predecessor_revision_digest(self) -> str:
        return self.predecessor.digest()

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ModelRevisionCommit:
    prepared: PreparedModelRevision
    validation_evidence: tuple[ModelRevisionEvidence, ...]
    commit_generation: int

    def __post_init__(self) -> None:
        if not isinstance(self.prepared, PreparedModelRevision):
            raise TypeError("model commit must carry PreparedModelRevision")
        object.__setattr__(
            self,
            "validation_evidence",
            _evidence(
                self.validation_evidence,
                field="model commit validation evidence",
                kind=ModelRevisionEvidenceKind.VALIDATION,
                revision_digest=self.prepared.candidate.digest(),
            ),
        )
        _generation(self.commit_generation, "model commit generation")

    @property
    def successor(self) -> ModelRevisionIdentity:
        return self.prepared.candidate

    @property
    def successor_revision_digest(self) -> str:
        return self.successor.digest()

    @property
    def predecessor_revision_digest(self) -> str:
        return self.prepared.predecessor.digest()

    def digest(self) -> str:
        return canonical_digest(self)


class ModelPromotionDisposition(StrEnum):
    PROMOTE = "promote"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class ModelPromotionDecision:
    candidate_revision_digest: str
    predecessor_active_revision_digest: str
    qualification_evidence: tuple[ModelRevisionEvidence, ...]
    evaluation_evidence: tuple[ModelRevisionEvidence, ...]
    disposition: ModelPromotionDisposition
    reason_digest: str
    policy_contract_id: str
    policy_implementation_digest: str
    policy_configuration_digest: str

    def __post_init__(self) -> None:
        candidate = _sha256(self.candidate_revision_digest, "model promotion candidate digest")
        predecessor = _sha256(
            self.predecessor_active_revision_digest, "model promotion predecessor digest"
        )
        if candidate == predecessor:
            raise ValueError("model promotion candidate must differ from active predecessor")
        object.__setattr__(
            self, "qualification_evidence",
            _evidence(
                self.qualification_evidence,
                field="model promotion qualification evidence",
                kind=ModelRevisionEvidenceKind.QUALIFICATION,
                revision_digest=candidate,
            ),
        )
        object.__setattr__(
            self, "evaluation_evidence",
            _evidence(
                self.evaluation_evidence,
                field="model promotion evaluation evidence",
                kind=ModelRevisionEvidenceKind.EVALUATION,
                revision_digest=candidate,
            ),
        )
        if not isinstance(self.disposition, ModelPromotionDisposition):
            raise TypeError("model promotion disposition must be typed")
        _sha256(self.reason_digest, "model promotion reason digest")
        _text(self.policy_contract_id, "model promotion policy contract id")
        _sha256(self.policy_implementation_digest, "model promotion policy implementation digest")
        _sha256(self.policy_configuration_digest, "model promotion policy configuration digest")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ModelPromotionReceipt:
    decision: ModelPromotionDecision
    activation_generation: int

    def __post_init__(self) -> None:
        if not isinstance(self.decision, ModelPromotionDecision):
            raise TypeError("model promotion receipt must carry ModelPromotionDecision")
        if self.decision.disposition is not ModelPromotionDisposition.PROMOTE:
            raise ValueError("rejected model revision cannot be promoted")
        _generation(self.activation_generation, "model promotion activation generation")

    @property
    def active_revision_digest(self) -> str:
        return self.decision.candidate_revision_digest

    @property
    def previous_active_revision_digest(self) -> str:
        return self.decision.predecessor_active_revision_digest

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ModelRollbackReceipt:
    failed_active_revision_digest: str
    rollback_target_revision_digest: str
    triggering_evidence: tuple[ModelRevisionEvidence, ...]
    recovery_anchor_digest: str
    rollback_generation: int

    def __post_init__(self) -> None:
        failed = _sha256(self.failed_active_revision_digest, "model rollback failed revision digest")
        target = _sha256(self.rollback_target_revision_digest, "model rollback target digest")
        if failed == target:
            raise ValueError("model rollback target must differ from failed active revision")
        object.__setattr__(
            self, "triggering_evidence",
            _evidence(
                self.triggering_evidence,
                field="model rollback triggering evidence",
                kind=ModelRevisionEvidenceKind.ROLLBACK_TRIGGER,
                revision_digest=failed,
            ),
        )
        _sha256(self.recovery_anchor_digest, "model rollback recovery anchor digest")
        _generation(self.rollback_generation, "model rollback generation")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ModelRevisionAuthoritySnapshot:
    authority_generation: int
    active_revision: ModelRevisionIdentity
    committed_revision_digests: tuple[str, ...]
    prepared_revision_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        _generation(self.authority_generation, "model revision authority generation")
        if not isinstance(self.active_revision, ModelRevisionIdentity):
            raise TypeError("model revision snapshot active revision must be typed")
        for field, values in (
            ("committed model revisions", self.committed_revision_digests),
            ("prepared model revisions", self.prepared_revision_digests),
        ):
            if not isinstance(values, tuple):
                raise TypeError(f"{field} must be a tuple")
            for digest in values:
                _sha256(digest, field)
            if len(set(values)) != len(values):
                raise ValueError(f"{field} must be unique")
        if self.active_revision.digest() not in self.committed_revision_digests:
            raise ValueError("active model revision must be committed")

    def digest(self) -> str:
        return canonical_digest(self)


@runtime_checkable
class ModelRevisionAuthorityPort(Protocol):
    def initialize(self, initial: ModelRevisionIdentity) -> ModelRevisionAuthoritySnapshot: ...

    def snapshot(self) -> ModelRevisionAuthoritySnapshot: ...

    def load_prepared(self, proposal_digest: str) -> PreparedModelRevision: ...

    def prepare_successor(
        self,
        build_receipt: "ModelUpdateBuildReceipt",
        *,
        expected_generation: int,
        recovery_anchor_digest: str,
        validation_plan_digest: str,
    ) -> PreparedModelRevision: ...

    def commit_successor(
        self,
        prepared: PreparedModelRevision,
        validation_evidence: tuple[ModelRevisionEvidence, ...],
        *,
        expected_generation: int,
    ) -> ModelRevisionCommit: ...

    def promote(
        self,
        decision: ModelPromotionDecision,
        *,
        expected_generation: int,
    ) -> ModelPromotionReceipt: ...

    def rollback(
        self,
        failed_active_revision_digest: str,
        rollback_target_revision_digest: str,
        triggering_evidence: tuple[ModelRevisionEvidence, ...],
        *,
        recovery_anchor_digest: str,
        expected_generation: int,
    ) -> ModelRollbackReceipt: ...


__all__ = [
    "ModelPromotionDecision",
    "ModelPromotionDisposition",
    "ModelPromotionReceipt",
    "ModelRevisionAuthorityPort",
    "ModelRevisionAuthoritySnapshot",
    "ModelRevisionCommit",
    "ModelRevisionConflictError",
    "ModelRevisionEvidence",
    "ModelRevisionEvidenceKind",
    "ModelRevisionIdentity",
    "ModelRevisionIntegrityError",
    "ModelRevisionStateError",
    "ModelRollbackReceipt",
    "ModelUpdateProposal",
    "PreparedModelRevision",
]
