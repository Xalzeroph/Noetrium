"""Journal-derived, read-only inspection for machines and runs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .canonical import canonical_digest
from .contracts import ChildMachineLink
from .delivery import MachineOutboxPort
from .journal import MachineJournalPort
from .machine import MachineCommit, MachineIdentity, MachineProgramRef


@dataclass(frozen=True, slots=True)
class MachineHistoryInspection:
    identity: MachineIdentity
    program: MachineProgramRef
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
            raise ValueError("inspection commit ids must match transitions")
        if self.revision != (0 if not self.transitions else self.transitions[-1].revision):
            raise ValueError("inspection revision must match journal head")
        object.__setattr__(
            self, "inspection_digest",
            canonical_digest({
                "identity": self.identity,
                "program": self.program,
                "revision": self.revision,
                "commit_ids": self.commit_ids,
                "transitions": self.transitions,
                "children": self.children,
                "effect_intent_refs": self.effect_intent_refs,
                "evidence_refs": self.evidence_refs,
                "artifact_refs": self.artifact_refs,
                "pending_command_ids": self.pending_command_ids,
            }),
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
        program: MachineProgramRef,
        journal: MachineJournalPort,
        outbox: MachineOutboxPort | None = None,
    ) -> None:
        if not isinstance(identity, MachineIdentity):
            raise TypeError("inspection identity must be MachineIdentity")
        if not isinstance(program, MachineProgramRef):
            raise TypeError("inspection program must be MachineProgramRef")
        if not isinstance(journal, MachineJournalPort):
            raise TypeError("inspection journal must implement MachineJournalPort")
        if outbox is not None and not isinstance(outbox, MachineOutboxPort):
            raise TypeError("inspection outbox must implement MachineOutboxPort")
        self.identity = identity
        self.program = program
        self.journal = journal
        self.outbox = outbox

    def inspect(self, machine_id: str) -> MachineHistoryInspection:
        if machine_id != self.identity.machine_id:
            raise ValueError("inspection machine_id does not match identity")
        transitions = self.journal.commits(machine_id)
        pending = () if self.outbox is None else tuple(
            envelope.command_id for envelope in self.outbox.pending()
            if envelope.machine_id == machine_id
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
            program=self.program,
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
