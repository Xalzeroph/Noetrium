from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .topology import (
    ParticipantArchitectureRevision,
    ParticipantArchitectureTransition,
    ParticipantTopology,
    ParticipantTopologyTransition,
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


def _generation(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _refs(values: object, field: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{field} must be a tuple")
    result = tuple(_text(value, field) for value in values)
    if len(set(result)) != len(result):
        raise ValueError(f"{field} must be unique")
    return result


class ParticipantRevisionConflictError(RuntimeError):
    """The caller observed a stale participant revision generation/current revision."""


class ParticipantRevisionIntegrityError(RuntimeError):
    """Durable participant revision state is corrupt or semantically inconsistent."""


class ParticipantRevisionStateError(RuntimeError):
    """The requested participant revision transition is illegal in current state."""


@dataclass(frozen=True, slots=True)
class ParticipantStateCompatibility:
    state_contract_id: str
    state_schema_digest: str
    codec_contract_id: str
    codec_implementation_digest: str

    def __post_init__(self) -> None:
        _text(self.state_contract_id, "participant state contract id")
        _sha256(self.state_schema_digest, "participant state schema digest")
        _text(self.codec_contract_id, "participant state codec contract id")
        _sha256(self.codec_implementation_digest, "participant state codec implementation digest")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ParticipantStateRevision:
    participant_id: str
    revision_id: str
    compatibility: ParticipantStateCompatibility
    implementation_digest: str
    configuration_digest: str
    state_artifact_digest: str
    predecessor_digest: str | None = None

    def __post_init__(self) -> None:
        _text(self.participant_id, "participant state participant_id")
        _text(self.revision_id, "participant state revision_id")
        if not isinstance(self.compatibility, ParticipantStateCompatibility):
            raise TypeError("participant state revision compatibility must be typed")
        _sha256(self.implementation_digest, "participant state implementation digest")
        _sha256(self.configuration_digest, "participant state configuration digest")
        _sha256(self.state_artifact_digest, "participant state artifact digest")
        if self.predecessor_digest is not None:
            _sha256(self.predecessor_digest, "participant state predecessor digest")

    @property
    def state_contract_id(self) -> str:
        return self.compatibility.state_contract_id

    def checkpoint_compatibility_digest(self) -> str:
        return self.compatibility.digest()

    def require_resume_compatible(self, checkpoint_compatibility_digest: str) -> None:
        _sha256(checkpoint_compatibility_digest, "participant state checkpoint compatibility digest")
        if checkpoint_compatibility_digest != self.checkpoint_compatibility_digest():
            raise ValueError("participant state schema/codec is incompatible with checkpoint")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ParticipantStateTransition:
    transition_id: str
    from_revision_digest: str
    to_revision_digest: str
    update_contract_id: str
    migration_adapter_digest: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.transition_id, "participant state transition id")
        _sha256(self.from_revision_digest, "participant state transition from digest")
        _sha256(self.to_revision_digest, "participant state transition to digest")
        if self.from_revision_digest == self.to_revision_digest:
            raise ValueError("participant state transition must change revision identity")
        _text(self.update_contract_id, "participant state update contract id")
        if self.migration_adapter_digest is not None:
            _sha256(self.migration_adapter_digest, "participant state migration adapter digest")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "participant state evidence refs"))

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ParticipantRevisionProposal:
    proposal_id: str
    predecessor_revision_digest: str
    update_contract_id: str
    reason_digest: str
    migration_adapter_digest: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.proposal_id, "participant revision proposal id")
        _sha256(self.predecessor_revision_digest, "participant revision proposal predecessor digest")
        _text(self.update_contract_id, "participant revision update contract id")
        _sha256(self.reason_digest, "participant revision reason digest")
        if self.migration_adapter_digest is not None:
            _sha256(self.migration_adapter_digest, "participant revision migration adapter digest")
        object.__setattr__(self, "evidence_refs", _refs(self.evidence_refs, "participant revision evidence refs"))

    def digest(self) -> str:
        return canonical_digest(self)


class ParticipantRevisionEvidenceKind(StrEnum):
    VALIDATION = "validation"
    MIGRATION = "migration"


@dataclass(frozen=True, slots=True)
class ParticipantRevisionEvidence:
    kind: ParticipantRevisionEvidenceKind
    revision_digest: str
    evidence_digest: str
    producer_contract_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ParticipantRevisionEvidenceKind):
            raise TypeError("participant revision evidence kind must be typed")
        _sha256(self.revision_digest, "participant revision evidence revision digest")
        _sha256(self.evidence_digest, "participant revision evidence digest")
        _text(self.producer_contract_id, "participant revision evidence producer contract id")

    def digest(self) -> str:
        return canonical_digest(self)


ParticipantRevisionValue = ParticipantTopology | ParticipantArchitectureRevision | ParticipantStateRevision
ParticipantTransitionValue = ParticipantTopologyTransition | ParticipantArchitectureTransition | ParticipantStateTransition


def _revision_predecessor(candidate: ParticipantRevisionValue) -> str | None:
    return candidate.predecessor_digest


def _transition_digests(transition: ParticipantTransitionValue) -> tuple[str, str]:
    if isinstance(transition, ParticipantTopologyTransition):
        return transition.from_topology_digest, transition.to_topology_digest
    return transition.from_revision_digest, transition.to_revision_digest


def _validate_topology_transition(
    before: ParticipantTopology,
    after: ParticipantTopology,
    transition: ParticipantTopologyTransition,
) -> None:
    before_map = {member.participant_id: member for member in before.members}
    after_map = {member.participant_id: member for member in after.members}
    changed = {
        participant_id
        for participant_id in before_map.keys() | after_map.keys()
        if before_map.get(participant_id) != after_map.get(participant_id)
    }
    if changed != {change.participant_id for change in transition.changes}:
        raise ValueError("participant topology change list does not reconstruct candidate")
    for change in transition.changes:
        before_member = before_map.get(change.participant_id)
        after_member = after_map.get(change.participant_id)
        before_digest = None if before_member is None else before_member.digest()
        after_digest = None if after_member is None else after_member.digest()
        if change.before_member_digest != before_digest or change.after_member_digest != after_digest:
            raise ValueError("participant topology change digest does not match source/target member")


def _validate_architecture_transition(
    before: ParticipantArchitectureRevision,
    after: ParticipantArchitectureRevision,
    transition: ParticipantArchitectureTransition,
) -> None:
    if transition.participant_id != before.participant_id or after.participant_id != before.participant_id:
        raise ValueError("participant architecture transition participant identity drift")
    before_map = {component.component_id: component for component in before.components}
    after_map = {component.component_id: component for component in after.components}
    changed = {
        component_id
        for component_id in before_map.keys() | after_map.keys()
        if before_map.get(component_id) != after_map.get(component_id)
    }
    if changed != {change.component_id for change in transition.changes}:
        raise ValueError("participant architecture change list does not reconstruct candidate")
    for change in transition.changes:
        before_component = before_map.get(change.component_id)
        after_component = after_map.get(change.component_id)
        before_digest = None if before_component is None else before_component.digest()
        after_digest = None if after_component is None else after_component.digest()
        if change.before_component_digest != before_digest or change.after_component_digest != after_digest:
            raise ValueError("participant architecture change digest does not match source/target component")


def _validation_evidence(
    values: object,
    *,
    revision_digest: str,
) -> tuple[ParticipantRevisionEvidence, ...]:
    if not isinstance(values, tuple) or not values:
        raise TypeError("participant revision validation evidence must be a non-empty tuple")
    if any(not isinstance(value, ParticipantRevisionEvidence) for value in values):
        raise TypeError("participant revision validation evidence must be typed")
    for value in values:
        if value.kind is not ParticipantRevisionEvidenceKind.VALIDATION:
            raise ValueError("participant revision commit requires validation evidence")
        if value.revision_digest != revision_digest:
            raise ValueError("participant revision validation evidence must bind exact candidate")
    digests = tuple(value.digest() for value in values)
    if len(set(digests)) != len(digests):
        raise ValueError("participant revision validation evidence must be unique")
    return values


@dataclass(frozen=True, slots=True)
class PreparedParticipantRevision:
    proposal: ParticipantRevisionProposal
    predecessor: ParticipantRevisionValue
    candidate: ParticipantRevisionValue
    transition: ParticipantTransitionValue
    preparation_generation: int
    recovery_anchor_digest: str
    validation_plan_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, ParticipantRevisionProposal):
            raise TypeError("prepared participant revision proposal must be typed")
        allowed = (ParticipantTopology, ParticipantArchitectureRevision, ParticipantStateRevision)
        if not isinstance(self.predecessor, allowed) or not isinstance(self.candidate, allowed):
            raise TypeError("prepared participant revisions must be typed")
        if type(self.predecessor) is not type(self.candidate):
            raise TypeError("prepared participant predecessor and candidate must share revision kind")
        predecessor_digest = self.predecessor.digest()
        candidate_digest = self.candidate.digest()
        if self.proposal.predecessor_revision_digest != predecessor_digest:
            raise ValueError("participant proposal does not bind exact predecessor")
        if candidate_digest == predecessor_digest:
            raise ValueError("prepared participant candidate must be a distinct revision")
        if _revision_predecessor(self.candidate) != predecessor_digest:
            raise ValueError("prepared participant candidate does not bind exact predecessor")
        self._validate_transition(predecessor_digest, candidate_digest)
        _generation(self.preparation_generation, "participant preparation generation")
        _sha256(self.recovery_anchor_digest, "participant revision recovery anchor digest")
        _sha256(self.validation_plan_digest, "participant revision validation plan digest")

    def _validate_transition(self, predecessor_digest: str, candidate_digest: str) -> None:
        expected = {
            ParticipantTopology: ParticipantTopologyTransition,
            ParticipantArchitectureRevision: ParticipantArchitectureTransition,
            ParticipantStateRevision: ParticipantStateTransition,
        }[type(self.candidate)]
        if not isinstance(self.transition, expected):
            raise TypeError("prepared participant transition kind does not match revision kind")
        from_digest, to_digest = _transition_digests(self.transition)
        if from_digest != predecessor_digest or to_digest != candidate_digest:
            raise ValueError("prepared participant transition does not bind predecessor/candidate")
        if isinstance(self.transition, ParticipantTopologyTransition):
            _validate_topology_transition(self.predecessor, self.candidate, self.transition)
        elif isinstance(self.transition, ParticipantArchitectureTransition):
            _validate_architecture_transition(self.predecessor, self.candidate, self.transition)
        else:
            self._validate_state_transition()

    def _validate_state_transition(self) -> None:
        assert isinstance(self.predecessor, ParticipantStateRevision)
        assert isinstance(self.candidate, ParticipantStateRevision)
        assert isinstance(self.transition, ParticipantStateTransition)
        if self.predecessor.participant_id != self.candidate.participant_id:
            raise ValueError("participant state update cannot change participant identity")
        if self.transition.update_contract_id != self.proposal.update_contract_id:
            raise ValueError("participant state transition update contract drift")
        if self.transition.migration_adapter_digest != self.proposal.migration_adapter_digest:
            raise ValueError("participant state transition migration adapter drift")
        compatibility_changed = (
            self.predecessor.checkpoint_compatibility_digest()
            != self.candidate.checkpoint_compatibility_digest()
        )
        if compatibility_changed and self.transition.migration_adapter_digest is None:
            raise ValueError("participant state compatibility change requires migration adapter")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ParticipantRevisionCommit:
    prepared: PreparedParticipantRevision
    validation_evidence: tuple[ParticipantRevisionEvidence, ...]
    commit_generation: int

    def __post_init__(self) -> None:
        if not isinstance(self.prepared, PreparedParticipantRevision):
            raise TypeError("participant revision commit must carry prepared revision")
        object.__setattr__(
            self,
            "validation_evidence",
            _validation_evidence(
                self.validation_evidence,
                revision_digest=self.prepared.candidate.digest(),
            ),
        )
        _generation(self.commit_generation, "participant revision commit generation")

    @property
    def successor_revision_digest(self) -> str:
        return self.prepared.candidate.digest()

    @property
    def predecessor_revision_digest(self) -> str:
        return self.prepared.predecessor.digest()

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ParticipantRevisionAuthoritySnapshot:
    authority_generation: int
    current_revision: ParticipantRevisionValue
    committed_revision_digests: tuple[str, ...]
    prepared_revision_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        _generation(self.authority_generation, "participant revision authority generation")
        allowed = (ParticipantTopology, ParticipantArchitectureRevision, ParticipantStateRevision)
        if not isinstance(self.current_revision, allowed):
            raise TypeError("participant revision current revision must be typed")
        for field, values in (
            ("committed participant revisions", self.committed_revision_digests),
            ("prepared participant revisions", self.prepared_revision_digests),
        ):
            if not isinstance(values, tuple):
                raise TypeError(f"{field} must be a tuple")
            for digest in values:
                _sha256(digest, field)
            if len(set(values)) != len(values):
                raise ValueError(f"{field} must be unique")
        if self.current_revision.digest() not in self.committed_revision_digests:
            raise ValueError("current participant revision must be committed")

    def digest(self) -> str:
        return canonical_digest(self)


@runtime_checkable
class ParticipantRevisionAuthorityPort(Protocol):
    def initialize(self, initial: ParticipantRevisionValue) -> ParticipantRevisionAuthoritySnapshot: ...

    def snapshot(self) -> ParticipantRevisionAuthoritySnapshot: ...

    def load_prepared(self, proposal_digest: str) -> PreparedParticipantRevision: ...

    def prepare_successor(
        self,
        proposal: ParticipantRevisionProposal,
        predecessor: ParticipantRevisionValue,
        candidate: ParticipantRevisionValue,
        transition: ParticipantTransitionValue,
        *,
        expected_generation: int,
        recovery_anchor_digest: str,
        validation_plan_digest: str,
    ) -> PreparedParticipantRevision: ...

    def commit_successor(
        self,
        prepared: PreparedParticipantRevision,
        validation_evidence: tuple[ParticipantRevisionEvidence, ...],
        *,
        expected_generation: int,
    ) -> ParticipantRevisionCommit: ...


__all__ = [
    "ParticipantRevisionAuthorityPort",
    "ParticipantRevisionAuthoritySnapshot",
    "ParticipantRevisionCommit",
    "ParticipantRevisionConflictError",
    "ParticipantRevisionEvidence",
    "ParticipantRevisionEvidenceKind",
    "ParticipantRevisionIntegrityError",
    "ParticipantRevisionProposal",
    "ParticipantRevisionStateError",
    "ParticipantRevisionValue",
    "ParticipantStateCompatibility",
    "ParticipantStateRevision",
    "ParticipantStateTransition",
    "ParticipantTransitionValue",
    "PreparedParticipantRevision",
]
