"""Typed remote-worker admission; workers produce candidates, never facts."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
from typing import Protocol, runtime_checkable

from .canonical import canonical_bytes, canonical_digest
from .machine import (
    MachineConflict,
    MachineIdentity,
    MachineKind,
    MachineProgramRef,
    MachineSnapshot,
    TransitionProposal,
)
from .nir import NIREnvelope


class WorkerAdmissionError(RuntimeError):
    """A worker response failed the kernel admission contract."""


class WorkerAuthenticationError(WorkerAdmissionError):
    """A worker response was not authenticated for this envelope."""


@dataclass(frozen=True, slots=True)
class WorkerAuthenticator:
    """Minimal shared-secret authenticator for a trusted transport boundary."""

    key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("worker authenticator key must be non-empty")

    def sign(self, envelope_digest: str, proposal_digest: str) -> str:
        material = canonical_bytes({
            "envelope_digest": envelope_digest,
            "proposal_digest": proposal_digest,
        })
        return hmac.new(self.key, material, hashlib.sha256).hexdigest()

    def verify(self, envelope_digest: str, proposal_digest: str, signature: str) -> bool:
        expected = self.sign(envelope_digest, proposal_digest)
        return hmac.compare_digest(expected, signature)


@dataclass(frozen=True, slots=True)
class WorkerAdmissionPolicy:
    machine_id: str
    machine_kind: MachineKind
    program_digest: str
    worker_id: str
    allowed_scopes: tuple[str, ...] = ()
    max_payload_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        for name, value in (
            ("machine_id", self.machine_id),
            ("program_digest", self.program_digest),
            ("worker_id", self.worker_id),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"worker policy {name} is required")
        if not isinstance(self.machine_kind, MachineKind):
            raise TypeError("worker policy machine_kind must be MachineKind")
        if self.max_payload_bytes < 1:
            raise ValueError("worker policy max_payload_bytes must be positive")
        if any(type(value) is not str or not value.strip() for value in self.allowed_scopes):
            raise ValueError("worker policy allowed_scopes must be non-empty text")


@dataclass(frozen=True, slots=True)
class WorkerReply:
    proposal: TransitionProposal
    signature: str

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, TransitionProposal) or not self.signature.strip():
            raise ValueError("worker reply requires a proposal and signature")


@dataclass(frozen=True, slots=True)
class WorkerCandidate:
    worker_id: str
    envelope: NIREnvelope
    proposal: TransitionProposal
    signature: str
    candidate_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_digest", canonical_digest({
            "worker_id": self.worker_id,
            "envelope": self.envelope,
            "proposal": self.proposal,
            "signature": self.signature,
        }))


@runtime_checkable
class RemoteWorkerPort(Protocol):
    def propose(self, envelope: NIREnvelope, state: MachineSnapshot) -> WorkerReply: ...


class WorkerAdmission:
    """Validate untrusted worker output before the local runtime commits it."""

    def __init__(
        self,
        *,
        identity: MachineIdentity,
        program: MachineProgramRef,
        policy: WorkerAdmissionPolicy,
        authenticator: WorkerAuthenticator,
    ) -> None:
        if identity.machine_id != policy.machine_id or identity.kind is not policy.machine_kind:
            raise ValueError("worker policy does not match machine identity")
        if program.program_digest != policy.program_digest:
            raise ValueError("worker policy does not match program")
        self.identity = identity
        self.program = program
        self.policy = policy
        self.authenticator = authenticator

    def admit(
        self,
        envelope: NIREnvelope,
        state: MachineSnapshot,
        reply: WorkerReply,
    ) -> WorkerCandidate:
        if envelope.machine_id != self.identity.machine_id:
            raise WorkerAdmissionError("worker envelope machine identity mismatch")
        if envelope.machine_kind is not self.identity.kind:
            raise WorkerAdmissionError("worker envelope machine kind mismatch")
        if envelope.program_digest != self.program.program_digest:
            raise WorkerAdmissionError("worker envelope program digest mismatch")
        if any(scope not in self.policy.allowed_scopes for scope in envelope.capability_scope):
            raise WorkerAdmissionError("worker envelope requests an unapproved capability scope")
        if len(canonical_bytes(envelope.payload)) > self.policy.max_payload_bytes:
            raise WorkerAdmissionError("worker payload exceeds the admission budget")
        if not self.authenticator.verify(
            envelope.envelope_digest,
            reply.proposal.proposal_digest,
            reply.signature,
        ):
            raise WorkerAuthenticationError("worker proposal attestation is invalid")
        if reply.proposal.machine_id != state.machine_id:
            raise WorkerAdmissionError("worker proposal machine identity mismatch")
        if reply.proposal.command_id != envelope.command_id:
            raise WorkerAdmissionError("worker proposal command identity mismatch")
        if reply.proposal.base_revision != state.revision:
            raise MachineConflict("worker proposal is based on a stale machine revision")
        return WorkerCandidate(
            self.policy.worker_id,
            envelope,
            reply.proposal,
            reply.signature,
        )


class AuthenticatedWorkerInterpreter:
    """Machine interpreter facade; only its proposal crosses into MachineRuntime."""

    def __init__(
        self,
        *,
        identity: MachineIdentity,
        program: MachineProgramRef,
        admission: WorkerAdmission,
        worker: RemoteWorkerPort,
    ) -> None:
        self.identity = identity
        self.program = program
        self.admission = admission
        if not isinstance(worker, RemoteWorkerPort):
            raise TypeError("worker must implement RemoteWorkerPort")
        self.worker = worker

    def propose(self, command, state: MachineSnapshot) -> TransitionProposal:
        envelope = NIREnvelope.from_command(
            version=1,
            machine_kind=self.identity.kind,
            program_digest=self.program.program_digest,
            command=command,
        )
        reply = self.worker.propose(envelope, state)
        candidate = self.admission.admit(envelope, state, reply)
        return candidate.proposal


__all__ = [
    "AuthenticatedWorkerInterpreter",
    "RemoteWorkerPort",
    "WorkerAdmission",
    "WorkerAdmissionError",
    "WorkerAdmissionPolicy",
    "WorkerAuthenticationError",
    "WorkerAuthenticator",
    "WorkerCandidate",
    "WorkerReply",
]
