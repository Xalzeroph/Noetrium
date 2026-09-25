from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import canonical_digest


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _sha256(value: object, field: str) -> str:
    digest = _text(value, field)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return digest


def _tokens(values: object, field: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{field} must be a tuple")
    result = tuple(_text(value, field) for value in values)
    if len(result) != len(set(result)):
        raise ValueError(f"{field} must be unique")
    return result


@dataclass(frozen=True, slots=True)
class ParticipantTopologyMember:
    participant_id: str
    role: str
    requirement_digest: str
    binding_digest: str
    architecture_revision_digest: str

    def __post_init__(self) -> None:
        _text(self.participant_id, "topology participant_id")
        _text(self.role, "topology role")
        _sha256(self.requirement_digest, "topology requirement_digest")
        _sha256(self.binding_digest, "topology binding_digest")
        _sha256(self.architecture_revision_digest, "topology architecture_revision_digest")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ParticipantTopology:
    topology_id: str
    members: tuple[ParticipantTopologyMember, ...]
    revision: int = 1
    predecessor_digest: str | None = None

    def __post_init__(self) -> None:
        _text(self.topology_id, "participant topology_id")
        if not isinstance(self.members, tuple) or not self.members:
            raise TypeError("participant topology members must be a non-empty tuple")
        if any(not isinstance(member, ParticipantTopologyMember) for member in self.members):
            raise TypeError("participant topology members must be typed")
        ids = tuple(member.participant_id for member in self.members)
        if len(ids) != len(set(ids)):
            raise ValueError("participant topology participant ids must be unique")
        if type(self.revision) is not int or self.revision <= 0:
            raise ValueError("participant topology revision must be positive")
        if self.revision == 1 and self.predecessor_digest is not None:
            raise ValueError("initial participant topology cannot have a predecessor")
        if self.revision > 1:
            _sha256(self.predecessor_digest, "participant topology predecessor_digest")
        object.__setattr__(self, "members", tuple(sorted(self.members, key=lambda row: row.participant_id)))

    def digest(self) -> str:
        return canonical_digest(self)

    def checkpoint_compatibility_digest(self) -> str:
        return canonical_digest({
            "topology_id": self.topology_id,
            "members": tuple((member.participant_id, member.role) for member in self.members),
        })

    def require_resume_compatible(self, checkpoint_compatibility_digest: str) -> None:
        _sha256(checkpoint_compatibility_digest, "checkpoint topology compatibility digest")
        if checkpoint_compatibility_digest != self.checkpoint_compatibility_digest():
            raise ValueError("participant topology structure is incompatible with checkpoint")


class TopologyChangeKind(StrEnum):
    ADD_MEMBER = "add-member"
    REMOVE_MEMBER = "remove-member"
    REPLACE_MEMBER = "replace-member"
    REBIND_MEMBER = "rebind-member"


@dataclass(frozen=True, slots=True)
class ParticipantTopologyChange:
    kind: TopologyChangeKind
    participant_id: str
    before_member_digest: str | None = None
    after_member_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TopologyChangeKind):
            raise TypeError("topology change kind must be typed")
        _text(self.participant_id, "topology change participant_id")
        before_required = self.kind is not TopologyChangeKind.ADD_MEMBER
        after_required = self.kind is not TopologyChangeKind.REMOVE_MEMBER
        if before_required:
            _sha256(self.before_member_digest, "topology change before_member_digest")
        elif self.before_member_digest is not None:
            raise ValueError("add-member change cannot carry before_member_digest")
        if after_required:
            _sha256(self.after_member_digest, "topology change after_member_digest")
        elif self.after_member_digest is not None:
            raise ValueError("remove-member change cannot carry after_member_digest")


@dataclass(frozen=True, slots=True)
class ParticipantTopologyTransition:
    transition_id: str
    from_topology_digest: str
    to_topology_digest: str
    changes: tuple[ParticipantTopologyChange, ...]
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.transition_id, "topology transition_id")
        _sha256(self.from_topology_digest, "topology transition from_digest")
        _sha256(self.to_topology_digest, "topology transition to_digest")
        if self.from_topology_digest == self.to_topology_digest:
            raise ValueError("topology transition must change topology identity")
        if not isinstance(self.changes, tuple) or not self.changes:
            raise TypeError("topology transition changes must be a non-empty tuple")
        if any(not isinstance(change, ParticipantTopologyChange) for change in self.changes):
            raise TypeError("topology transition changes must be typed")
        participant_ids = tuple(change.participant_id for change in self.changes)
        if len(participant_ids) != len(set(participant_ids)):
            raise ValueError("topology transition may change each participant at most once")
        object.__setattr__(self, "evidence_refs", _tokens(self.evidence_refs, "topology transition evidence_refs"))

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ParticipantMessageScheduleEntry:
    message_id: str
    sender_participant_id: str
    recipient_participant_ids: tuple[str, ...]
    sequence: int
    causal_parent_message_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.message_id, "message schedule message_id")
        _text(self.sender_participant_id, "message schedule sender_participant_id")
        recipients = _tokens(self.recipient_participant_ids, "message schedule recipients")
        if not recipients:
            raise ValueError("message schedule requires at least one recipient")
        object.__setattr__(self, "recipient_participant_ids", tuple(sorted(recipients)))
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("message schedule sequence must be a non-negative integer")
        parents = _tokens(self.causal_parent_message_ids, "message schedule causal parents")
        if self.message_id in parents:
            raise ValueError("message cannot causally depend on itself")
        object.__setattr__(self, "causal_parent_message_ids", tuple(sorted(parents)))

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ParticipantMessageSchedule:
    schedule_id: str
    topology_digest: str
    participant_ids: tuple[str, ...]
    entries: tuple[ParticipantMessageScheduleEntry, ...]

    def __post_init__(self) -> None:
        _text(self.schedule_id, "participant message schedule_id")
        _sha256(self.topology_digest, "participant message topology_digest")
        participant_ids = tuple(sorted(_tokens(self.participant_ids, "message schedule participant_ids")))
        if not participant_ids:
            raise ValueError("message schedule requires participant identities")
        object.__setattr__(self, "participant_ids", participant_ids)
        if not isinstance(self.entries, tuple) or not self.entries:
            raise TypeError("message schedule entries must be a non-empty tuple")
        if any(not isinstance(entry, ParticipantMessageScheduleEntry) for entry in self.entries):
            raise TypeError("message schedule entries must be typed")
        ordered = tuple(sorted(self.entries, key=lambda row: row.sequence))
        sequences = tuple(entry.sequence for entry in ordered)
        if sequences != tuple(range(len(ordered))):
            raise ValueError("message schedule sequences must form a contiguous zero-based order")
        ids = tuple(entry.message_id for entry in ordered)
        if len(ids) != len(set(ids)):
            raise ValueError("message schedule message ids must be unique")
        known = set(participant_ids)
        seen_messages: set[str] = set()
        for entry in ordered:
            if entry.sender_participant_id not in known:
                raise ValueError("message schedule sender is not in topology participant set")
            if any(recipient not in known for recipient in entry.recipient_participant_ids):
                raise ValueError("message schedule recipient is not in topology participant set")
            if any(parent not in seen_messages for parent in entry.causal_parent_message_ids):
                raise ValueError("message schedule causal parents must precede dependent message")
            seen_messages.add(entry.message_id)
        object.__setattr__(self, "entries", ordered)

    @classmethod
    def for_topology(
        cls,
        schedule_id: str,
        topology: ParticipantTopology,
        entries: tuple[ParticipantMessageScheduleEntry, ...],
    ) -> "ParticipantMessageSchedule":
        if not isinstance(topology, ParticipantTopology):
            raise TypeError("message schedule topology must be typed")
        return cls(
            schedule_id=schedule_id,
            topology_digest=topology.digest(),
            participant_ids=tuple(member.participant_id for member in topology.members),
            entries=entries,
        )

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ParticipantArchitectureComponent:
    component_id: str
    capability_id: str
    implementation_digest: str
    configuration_digest: str
    state_schema_id: str = "none"

    def __post_init__(self) -> None:
        _text(self.component_id, "architecture component_id")
        _text(self.capability_id, "architecture capability_id")
        _sha256(self.implementation_digest, "architecture implementation_digest")
        _sha256(self.configuration_digest, "architecture configuration_digest")
        _text(self.state_schema_id, "architecture state_schema_id")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ParticipantArchitectureRevision:
    participant_id: str
    revision_id: str
    components: tuple[ParticipantArchitectureComponent, ...]
    predecessor_digest: str | None = None

    def __post_init__(self) -> None:
        _text(self.participant_id, "architecture participant_id")
        _text(self.revision_id, "architecture revision_id")
        if not isinstance(self.components, tuple) or not self.components:
            raise TypeError("architecture revision components must be a non-empty tuple")
        if any(not isinstance(component, ParticipantArchitectureComponent) for component in self.components):
            raise TypeError("architecture revision components must be typed")
        ids = tuple(component.component_id for component in self.components)
        if len(ids) != len(set(ids)):
            raise ValueError("architecture revision component ids must be unique")
        object.__setattr__(self, "components", tuple(sorted(self.components, key=lambda row: row.component_id)))
        if self.predecessor_digest is not None:
            _sha256(self.predecessor_digest, "architecture revision predecessor_digest")

    def digest(self) -> str:
        return canonical_digest(self)

    def checkpoint_compatibility_digest(self) -> str:
        return canonical_digest({
            "participant_id": self.participant_id,
            "components": tuple(
                (component.component_id, component.state_schema_id) for component in self.components
            ),
        })

    def require_resume_compatible(self, checkpoint_compatibility_digest: str) -> None:
        _sha256(checkpoint_compatibility_digest, "checkpoint architecture compatibility digest")
        if checkpoint_compatibility_digest != self.checkpoint_compatibility_digest():
            raise ValueError("participant architecture state schema is incompatible with checkpoint")


class ArchitectureChangeKind(StrEnum):
    ADD_COMPONENT = "add-component"
    REMOVE_COMPONENT = "remove-component"
    REPLACE_COMPONENT = "replace-component"
    RECONFIGURE_COMPONENT = "reconfigure-component"


@dataclass(frozen=True, slots=True)
class ParticipantArchitectureChange:
    kind: ArchitectureChangeKind
    component_id: str
    before_component_digest: str | None = None
    after_component_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ArchitectureChangeKind):
            raise TypeError("architecture change kind must be typed")
        _text(self.component_id, "architecture change component_id")
        before_required = self.kind is not ArchitectureChangeKind.ADD_COMPONENT
        after_required = self.kind is not ArchitectureChangeKind.REMOVE_COMPONENT
        if before_required:
            _sha256(self.before_component_digest, "architecture change before_component_digest")
        elif self.before_component_digest is not None:
            raise ValueError("add-component change cannot carry before_component_digest")
        if after_required:
            _sha256(self.after_component_digest, "architecture change after_component_digest")
        elif self.after_component_digest is not None:
            raise ValueError("remove-component change cannot carry after_component_digest")


@dataclass(frozen=True, slots=True)
class ParticipantArchitectureTransition:
    transition_id: str
    participant_id: str
    from_revision_digest: str
    to_revision_digest: str
    changes: tuple[ParticipantArchitectureChange, ...]
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.transition_id, "architecture transition_id")
        _text(self.participant_id, "architecture transition participant_id")
        _sha256(self.from_revision_digest, "architecture transition from_revision_digest")
        _sha256(self.to_revision_digest, "architecture transition to_revision_digest")
        if self.from_revision_digest == self.to_revision_digest:
            raise ValueError("architecture transition must change revision identity")
        if not isinstance(self.changes, tuple) or not self.changes:
            raise TypeError("architecture transition changes must be a non-empty tuple")
        if any(not isinstance(change, ParticipantArchitectureChange) for change in self.changes):
            raise TypeError("architecture transition changes must be typed")
        component_ids = tuple(change.component_id for change in self.changes)
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("architecture transition may change each component at most once")
        object.__setattr__(self, "evidence_refs", _tokens(self.evidence_refs, "architecture transition evidence_refs"))

    def digest(self) -> str:
        return canonical_digest(self)


__all__ = [
    "ArchitectureChangeKind",
    "ParticipantArchitectureChange",
    "ParticipantArchitectureComponent",
    "ParticipantArchitectureRevision",
    "ParticipantArchitectureTransition",
    "ParticipantMessageSchedule",
    "ParticipantMessageScheduleEntry",
    "ParticipantTopology",
    "ParticipantTopologyChange",
    "ParticipantTopologyMember",
    "ParticipantTopologyTransition",
    "TopologyChangeKind",
]
