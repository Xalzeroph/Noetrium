"""Journal-derived, read-only inspection for machines and runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from .canonical import canonical_digest, thaw_json
from .contracts import ChildMachineLink
from .delivery import MachineOutboxPort
from .journal import MachineJournalPort
from .machine import MachineCommit, MachineIdentity, ExecutableUnitRef, MachineIntegrityError


def iter_machine_commit_event_units(commits: tuple[MachineCommit, ...]) -> Iterator["NoetriumUnit"]:
    """Project committed events without persisting a second truth store."""
    from noetrium_platform.foundation.kernel.unit import NoetriumUnit

    for commit in commits:
        for index, event in enumerate(commit.event_payloads):
            event_key = canonical_digest({
                "commit_id": commit.commit_id,
                "event_index": index,
            })
            yield NoetriumUnit(
                f"machine-event:{event_key}",
                schemas=("machine.accepted-event.v1",),
                attributes={
                    "kind": "committed-event-projection",
                    "authority": "machine-journal",
                    "machine_id": commit.machine_id,
                    "unit_digest": commit.unit_digest,
                    "source_commit_id": commit.commit_id,
                    "previous_commit_id": commit.previous_commit_id,
                    "revision": commit.revision,
                    "event_index": index,
                    "payload": thaw_json(event),
                },
            )




@dataclass(frozen=True, slots=True)
class MachineHistoryInspection:
    identity: MachineIdentity
    unit: ExecutableUnitRef
    revision: int
    commit_ids: tuple[str, ...]
    transitions: tuple[MachineCommit, ...]
    children: tuple[ChildMachineLink, ...]
    effect_intent_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    pending_command_ids: tuple[str, ...]
    inspection_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("inspection revision must be non-negative")
        if len(self.commit_ids) != len(self.transitions):
            raise MachineIntegrityError("inspection commit ids must match transitions")
        if self.revision != (0 if not self.transitions else self.transitions[-1].revision):
            raise MachineIntegrityError("inspection revision must match journal head")

        # One linear-time proof over the exact accepted Machine history. These
        # facts are not a second ledger; each commit_id already commits to every
        # field, including the events, state delta, effects and evidence refs.
        previous_id = None
        previous_state_digest = None
        for expected_revision, (commit_id, commit) in enumerate(
            zip(self.commit_ids, self.transitions), start=1
        ):
            if (
                commit.machine_id != self.identity.machine_id
                or commit.unit_digest != self.unit.unit_digest
                or commit.execution_lock_digest != self.unit.execution_lock.lock_digest
                or commit.commit_id != commit_id
                or commit.base_revision != expected_revision - 1
                or commit.revision != expected_revision
                or commit.previous_commit_id != previous_id
                or (previous_state_digest is not None
                    and commit.before_state_digest != previous_state_digest)
            ):
                raise MachineIntegrityError(
                    f"machine journal coverage failed at revision {expected_revision}"
                )
            previous_id = commit_id
            previous_state_digest = commit.state_digest
        if self.children != tuple(
            child for commit in self.transitions for child in commit.child_links
        ):
            raise MachineIntegrityError("machine inspection child projection drifted")
        for name, values, field_name in (
            ("effect", self.effect_intent_refs, "effect_intent_refs"),
            ("evidence", self.evidence_refs, "evidence_refs"),
            ("artifact", self.artifact_refs, "artifact_refs"),
        ):
            if values != tuple(
                ref for commit in self.transitions
                for ref in getattr(commit, field_name)
            ):
                raise MachineIntegrityError(f"machine inspection {name} projection drifted")
        # O(number of commits + deliveries), not O(sum of historical state sizes).
        # SHA-256 commit IDs bind all authoritative commit fields; hashing whole
        # frozen MachineCommit objects would repeatedly hash states and events.
        object.__setattr__(
            self, "inspection_digest",
            canonical_digest({
                "schema": "machine.journal-inspection.v2",
                "machine_id": self.identity.machine_id,
                "unit_digest": self.unit.unit_digest,
                "execution_lock_digest": self.unit.execution_lock.lock_digest,
                "revision": self.revision,
                "commit_ids": self.commit_ids,
                "pending_command_ids": self.pending_command_ids,
            }),
        )

    def iter_accepted_event_units(self) -> "Iterator[NoetriumUnit]":
        """Stream accepted events through the unique generic projection."""
        return iter_machine_commit_event_units(self.transitions)

    def accepted_event_units(self) -> tuple["NoetriumUnit", ...]:
        """Materialize the same streaming journal-derived projection on demand."""
        return tuple(self.iter_accepted_event_units())

    def journal_coverage_unit(self) -> "NoetriumUnit":
        """Attest this *committed journal cut*, never unseen physical facts.

        Content references/effects require their own authority verification;
        they cannot be certified from a Machine Journal alone.
        """
        # Avoid importing the enclosing Unit carrier during kernel init.
        from noetrium_platform.foundation.kernel.unit import NoetriumUnit

        journal_cut_digest = canonical_digest({
            "schema": "machine.accepted-journal-cut.v1",
            "machine_id": self.identity.machine_id,
            "unit_digest": self.unit.unit_digest,
            "execution_lock_digest": self.unit.execution_lock.lock_digest,
            "commit_ids": self.commit_ids,
        })
        return NoetriumUnit(
            f"machine-journal-coverage:{journal_cut_digest}",
            schemas=("machine.journal-coverage.v1",),
            attributes={
                "kind": "derived-evidence",
                "coverage_scope": "committed-machine-journal",
                "machine_id": self.identity.machine_id,
                "head_commit_id": (None if not self.commit_ids else self.commit_ids[-1]),
                "revision": self.revision,
                "journal_cut_digest": journal_cut_digest,
                "event_count": sum(len(c.event_payloads) for c in self.transitions),
                "effect_intent_count": len(self.effect_intent_refs),
                "evidence_reference_count": len(self.evidence_refs),
                "artifact_reference_count": len(self.artifact_refs),
                # Outbox delivery state is a mutable projection, not part of
                # the immutable accepted Journal cut or its scientific proof.
                "external_effects_verified": False,
                "referenced_artifacts_verified": False,
            },
        )


@runtime_checkable
class JournalInspectionPort(Protocol):
    def inspect(self, machine_id: str) -> MachineHistoryInspection: ...
class JournalInspectionService(JournalInspectionPort):
    """Build every durable field from the journal and delivery projection."""

    def __init__(
        self,
        *,
        identity: MachineIdentity,
        unit: ExecutableUnitRef,
        journal: MachineJournalPort,
        outbox: MachineOutboxPort | None = None,
    ) -> None:
        if not isinstance(identity, MachineIdentity):
            raise TypeError("inspection identity must be MachineIdentity")
        if not isinstance(unit, ExecutableUnitRef):
            raise TypeError("inspection unit must be ExecutableUnitRef")
        if not isinstance(journal, MachineJournalPort):
            raise TypeError("inspection journal must implement MachineJournalPort")
        if outbox is not None and not isinstance(outbox, MachineOutboxPort):
            raise TypeError("inspection outbox must implement MachineOutboxPort")
        self.identity = identity
        self.unit = unit
        self.journal = journal
        self.outbox = outbox

    def inspect(self, machine_id: str) -> MachineHistoryInspection:
        if machine_id != self.identity.machine_id:
            raise ValueError("inspection machine_id does not match identity")
        transitions = self.journal.commits(machine_id)
        pending = () if self.outbox is None else tuple(
            envelope.command.command_id
            for envelope in self.outbox.pending()
            if envelope.source_machine_id == machine_id
        )
        children = tuple(
            child for commit in transitions for child in commit.child_links
        )
        effect_refs = tuple(
            ref for commit in transitions for ref in commit.effect_intent_refs
        )
        evidence_refs = tuple(ref for commit in transitions for ref in commit.evidence_refs)
        artifact_refs = tuple(ref for commit in transitions for ref in commit.artifact_refs)
        return MachineHistoryInspection(
            identity=self.identity,
            unit=self.unit,
            revision=0 if not transitions else transitions[-1].revision,
            commit_ids=tuple(commit.commit_id for commit in transitions),
            transitions=transitions,
            children=children,
            effect_intent_refs=effect_refs,
            evidence_refs=evidence_refs,
            artifact_refs=artifact_refs,
            pending_command_ids=pending,
        )


__all__ = ["JournalInspectionPort", "JournalInspectionService", "MachineHistoryInspection"]
