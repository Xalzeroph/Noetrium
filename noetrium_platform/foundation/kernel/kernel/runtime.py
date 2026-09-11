"""Authoritative local runtime for the shared Machine ABI.

The runtime is deliberately small: it validates commands, asks a domain
interpreter for a proposal, turns that proposal into one immutable commit,
and lets the journal decide whether that commit becomes fact.
"""

from __future__ import annotations

from dataclasses import replace
from threading import RLock
from typing import Protocol, runtime_checkable

from .authority import MachineAuthorityPort, MachineLease
from .canonical import canonical_digest, thaw_json
from .contracts import CapabilityDescriptor
from .resources import ResourceBudget, ResourceSchedulerPort
from .delivery import MachineEnvelope, MachineOutboxPort
from .family import MachineFamilyDescriptor
from .journal import MachineJournalPort
from .json_value import JsonObject
from .snapshot import MachineSnapshotStorePort
from .machine import (
    MachineCommand,
    MachineCommit,
    MachineConflict,
    MachineIdentity,
    MachineInspection,
    MachineIntegrityError,
    MachineProgramRef,
    MachineSnapshot,
    MachineStatus,
    TransitionProposal,
)


class MachineRuntimeError(RuntimeError):
    """The local runtime cannot accept the requested operation."""


class MachineNotOpen(MachineRuntimeError):
    """A step/checkpoint was requested before the machine was opened."""


@runtime_checkable
class MachineInterpreterPort(Protocol):
    def propose(
        self,
        command: MachineCommand,
        state: MachineSnapshot,
    ) -> TransitionProposal: ...


class MachineRuntime:
    """Single-machine coordinator with journal-backed authority."""

    def __init__(
        self,
        *,
        identity: MachineIdentity,
        program: MachineProgramRef,
        journal: MachineJournalPort,
        snapshot_store: MachineSnapshotStorePort | None = None,
        outbox: MachineOutboxPort | None = None,
        family: MachineFamilyDescriptor | None = None,
        capabilities: tuple[CapabilityDescriptor, ...] = (),
        resource_scheduler: ResourceSchedulerPort | None = None,
        resource_budget: ResourceBudget | None = None,
        authority: MachineAuthorityPort | None = None,
        authority_lease: MachineLease | None = None,
    ) -> None:
        self.identity = identity
        self.program = program
        self.journal = journal
        if snapshot_store is not None and not isinstance(snapshot_store, MachineSnapshotStorePort):
            raise TypeError("snapshot_store must implement MachineSnapshotStorePort")
        if outbox is not None and not isinstance(outbox, MachineOutboxPort):
            raise TypeError("outbox must implement MachineOutboxPort")
        if family is not None and not isinstance(family, MachineFamilyDescriptor):
            raise TypeError("family must be MachineFamilyDescriptor")
        if family is not None and family.kind is not identity.kind:
            raise ValueError("machine family kind must match machine identity kind")
        if family is not None and family.implementation_version != identity.implementation_version:
            raise ValueError("machine family implementation version must match machine identity")
        if type(capabilities) is not tuple or any(
            not isinstance(item, CapabilityDescriptor) for item in capabilities
        ):
            raise TypeError("capabilities must be a tuple of CapabilityDescriptor")
        capability_ids = tuple(item.capability_id for item in capabilities)
        if len(set(capability_ids)) != len(capability_ids):
            raise ValueError("capability identities must be unique")
        if family is not None:
            missing = set(family.required_capabilities) - set(capability_ids)
            if missing:
                raise ValueError(f"required machine capabilities are not granted: {sorted(missing)}")
        if resource_scheduler is not None and not isinstance(resource_scheduler, ResourceSchedulerPort):
            raise TypeError("resource_scheduler must implement ResourceSchedulerPort")
        if (resource_scheduler is None) != (resource_budget is None):
            raise ValueError("resource_scheduler and resource_budget must be provided together")
        if resource_budget is not None and not isinstance(resource_budget, ResourceBudget):
            raise TypeError("resource_budget must be ResourceBudget")
        if authority is not None and not isinstance(authority, MachineAuthorityPort):
            raise TypeError("authority must implement MachineAuthorityPort")
        if (authority is None) != (authority_lease is None):
            raise ValueError("authority and authority_lease must be provided together")
        if authority_lease is not None and authority_lease.machine_id != identity.machine_id:
            raise ValueError("authority lease belongs to a different machine")
        self.snapshot_store = snapshot_store
        self.outbox = outbox
        self.family = family
        self.capabilities = capabilities
        self.resource_scheduler = resource_scheduler
        self.resource_budget = resource_budget
        self.authority = authority
        self.authority_lease = authority_lease
        self._lock = RLock()
        self._snapshot: MachineSnapshot | None = None
        self._status = MachineStatus.READY

    @property
    def machine_id(self) -> str:
        return self.identity.machine_id

    def open(self, initial_state: JsonObject | None = None) -> MachineSnapshot:
        with self._lock:
            latest = self.journal.latest(self.machine_id)
            if latest is not None:
                self._snapshot = MachineSnapshot(
                    machine_id=self.machine_id,
                    revision=latest.revision,
                    program=self.program,
                    state=latest.state,
                    parent_commit_id=latest.commit_id,
                )
                self._status = MachineStatus.RUNNABLE
                if self.outbox is not None:
                    self.reconcile_outbox()
                return self._snapshot
            if self._snapshot is None:
                stored = None if self.snapshot_store is None else self.snapshot_store.load(self.machine_id)
                if stored is not None:
                    if stored.program != self.program or stored.revision != 0:
                        raise MachineIntegrityError("orphan snapshot cannot be used without its journal")
                    self._snapshot = stored
                else:
                    self._snapshot = MachineSnapshot(
                        machine_id=self.machine_id,
                        revision=0,
                        program=self.program,
                        state={} if initial_state is None else initial_state,
                        parent_commit_id=None,
                    )
            return self._snapshot
    def checkpoint(self) -> MachineSnapshot:
        with self._lock:
            if self._snapshot is None:
                raise MachineNotOpen("machine must be opened before checkpoint")
            if self.snapshot_store is not None:
                self.snapshot_store.save(self._snapshot)
            return self._snapshot

    def restore(self, snapshot: MachineSnapshot) -> MachineSnapshot:
        if not isinstance(snapshot, MachineSnapshot):
            raise TypeError("restore expects MachineSnapshot")
        if snapshot.machine_id != self.machine_id:
            raise MachineConflict("snapshot belongs to a different machine")
        if snapshot.program != self.program:
            raise MachineConflict("snapshot belongs to a different program")
        with self._lock:
            latest = self.journal.latest(self.machine_id)
            expected_revision = 0 if latest is None else latest.revision
            expected_parent = None if latest is None else latest.commit_id
            if snapshot.revision != expected_revision:
                raise MachineConflict(
                    f"cannot restore non-head snapshot: expected={expected_revision} "
                    f"actual={snapshot.revision}"
                )
            if snapshot.parent_commit_id != expected_parent:
                raise MachineConflict("snapshot parent does not match journal head")
            self._snapshot = snapshot
            if self.snapshot_store is not None:
                self.snapshot_store.save(snapshot)
            self._status = MachineStatus.RUNNABLE
            return snapshot

    def _require_open(self) -> MachineSnapshot:
        if self._snapshot is None:
            raise MachineNotOpen("machine must be opened before stepping")
        return self._snapshot

    def _assert_authority(self) -> None:
        if self.authority is not None and self.authority_lease is not None:
            self.authority.assert_held(self.authority_lease)


    def _existing_command(self, command: MachineCommand) -> MachineCommit | None:
        for commit in self.journal.commits(self.machine_id):
            if commit.command_id != command.command_id:
                continue
            if commit.command_digest != command.payload_digest:
                raise MachineConflict(
                    "command_id was already committed with a different payload"
                )
            return commit
        return None

    @staticmethod
    def _validate_proposal(
        command: MachineCommand,
        state: MachineSnapshot,
        proposal: TransitionProposal,
    ) -> None:
        if not isinstance(proposal, TransitionProposal):
            raise TypeError("interpreter must return TransitionProposal")
        if proposal.machine_id != command.machine_id:
            raise MachineRuntimeError("proposal machine_id does not match command")
        if proposal.command_id != command.command_id:
            raise MachineRuntimeError("proposal command_id does not match command")
        if proposal.base_revision != state.revision:
            raise MachineConflict(
                f"proposal based on revision {proposal.base_revision}, "
                f"runtime head is {state.revision}"
            )
        for emitted in proposal.emitted_commands:
            if emitted.command_id == command.command_id:
                raise MachineRuntimeError(
                    "a transition cannot emit its own command as a child"
                )

    def step(
        self,
        command: MachineCommand,
        interpreter: MachineInterpreterPort,
    ) -> MachineCommit:
        if not isinstance(command, MachineCommand):
            raise TypeError("step expects MachineCommand")
        if not isinstance(interpreter, MachineInterpreterPort):
            raise TypeError("interpreter must implement MachineInterpreterPort")
        if command.machine_id != self.machine_id:
            raise MachineConflict("command belongs to a different machine")
        if self.family is not None and self.family.command_kinds and command.kind not in self.family.command_kinds:
            raise MachineConflict(f"command kind is not admitted by machine family: {command.kind}")
        if self.capabilities:
            granted_scopes = {
                scope for capability in self.capabilities for scope in capability.permission_scope
            }
            denied = set(command.scope) - granted_scopes
            if denied:
                raise MachineConflict(f"command capability scope is not granted: {sorted(denied)}")
        with self._lock:
            existing = self._existing_command(command)
            if existing is not None:
                self._snapshot = MachineSnapshot(
                    machine_id=self.machine_id,
                    revision=existing.revision,
                    program=self.program,
                    state=existing.state,
                    parent_commit_id=existing.commit_id,
                )
                if self.outbox is not None:
                    self.outbox.enqueue(existing)
                return existing
            self._assert_authority()
            state = self._require_open()
            if command.expected_revision != state.revision:
                raise MachineConflict(
                    f"stale command revision: expected={state.revision} "
                    f"actual={command.expected_revision}"
                )
            resource_lease = None
            if self.resource_scheduler is not None and self.resource_budget is not None:
                resource_lease = self.resource_scheduler.acquire(
                    f"{self.machine_id}:{command.command_id}", self.resource_budget
                )
            try:
                proposal = interpreter.propose(command, state)
                self._validate_proposal(command, state, proposal)
            finally:
                if resource_lease is not None:
                    self.resource_scheduler.release(resource_lease)

            proposal = replace(
                proposal,
                before_state_digest=canonical_digest(state.state),
                input_digest=command.payload_digest,
                program_digest=self.program.program_digest,
                machine_kind=self.identity.kind.value,
                machine_version=self.identity.implementation_version,
                state_delta_ref=canonical_digest(proposal.state_delta),
                parent_transition_id=state.parent_commit_id,
                attempt_id=canonical_digest({
                    "command_id": command.command_id,
                    "base_revision": state.revision,
                    "worker": "machine-runtime",
                }),
                authority_epoch=(
                    None if self.authority_lease is None else self.authority_lease.epoch
                ),
            )
            merged = thaw_json(state.state)
            if not isinstance(merged, dict):
                raise MachineRuntimeError("machine state must be an object")
            merged.update(thaw_json(proposal.state_delta))
            self._assert_authority()
            commit = MachineCommit(
                machine_id=self.machine_id,
                command_id=command.command_id,
                base_revision=state.revision,
                revision=state.revision + 1,
                proposal_digest=proposal.proposal_digest,
                command_digest=command.payload_digest,
                state=merged,
                output_refs=proposal.output_refs,
                event_payloads=proposal.event_payloads,
                effect_intent_refs=proposal.effect_intent_refs,
                emitted_commands=proposal.emitted_commands,
                previous_commit_id=state.parent_commit_id,
                before_state_digest=proposal.before_state_digest,
                input_digest=proposal.input_digest,
                program_digest=proposal.program_digest,
                machine_kind=proposal.machine_kind,
                machine_version=proposal.machine_version,
                input_refs=proposal.input_refs,
                state_delta_ref=proposal.state_delta_ref,
                evidence_refs=proposal.evidence_refs,
                artifact_refs=proposal.artifact_refs,
                parent_transition_id=proposal.parent_transition_id,
                attempt_id=proposal.attempt_id,
                authority_epoch=proposal.authority_epoch,
                child_links=proposal.child_links,
            )
            accepted = self.journal.append(commit)
            self._snapshot = MachineSnapshot(
                machine_id=self.machine_id,
                revision=accepted.revision,
                program=self.program,
                state=accepted.state,
                parent_commit_id=accepted.commit_id,
            )
            if self.outbox is not None:
                self.outbox.enqueue(accepted)
            self._status = (
                MachineStatus.WAITING
                if proposal.wait_reason is not None
                else MachineStatus.RUNNABLE
            )
            return accepted

    def replay(self, revision: int | None = None) -> MachineSnapshot:
        """Reconstruct a verified snapshot from the authoritative journal."""
        with self._lock:
            history = self.journal.commits(self.machine_id)
            if not history:
                return self.open()
            selected = None
            previous = None
            states = {}
            for commit in history:
                if commit.machine_id != self.machine_id:
                    raise MachineIntegrityError("journal contains a foreign machine commit")
                if commit.program_digest is not None and commit.program_digest != self.program.program_digest:
                    raise MachineIntegrityError("journal commit belongs to a different program")
                if commit.previous_commit_id != previous:
                    raise MachineIntegrityError("journal replay predecessor chain is invalid")
                if commit.before_state_digest is not None and previous is not None:
                    if commit.before_state_digest != canonical_digest(states[previous]):
                        raise MachineIntegrityError("journal replay before_state_digest mismatch")
                states[commit.commit_id] = commit.state
                previous = commit.commit_id
                if revision is None or commit.revision <= revision:
                    selected = commit
            if selected is None:
                raise MachineConflict("requested replay revision is outside journal history")
            self._snapshot = MachineSnapshot(
                machine_id=self.machine_id,
                revision=selected.revision,
                program=self.program,
                state=selected.state,
                parent_commit_id=selected.commit_id,
            )
            self._status = MachineStatus.RUNNABLE
            return self._snapshot

    def reconcile_outbox(self) -> tuple[MachineEnvelope, ...]:
        if self.outbox is None:
            return ()
        with self._lock:
            return self.outbox.reconcile(self.journal.commits(self.machine_id))

    def inspect(self) -> MachineInspection:
        with self._lock:
            snapshot = self._require_open()
            latest = self.journal.latest(self.machine_id)
            return MachineInspection(
                identity=self.identity,
                program=self.program,
                status=self._status,
                revision=snapshot.revision,
                state_digest=canonical_digest(snapshot.state),
                last_commit_id=None if latest is None else latest.commit_id,
            )


__all__ = [
    "MachineInterpreterPort",
    "MachineNotOpen",
    "MachineRuntime",
    "MachineRuntimeError",
]
