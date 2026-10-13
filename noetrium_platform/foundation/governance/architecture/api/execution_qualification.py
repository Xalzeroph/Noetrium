"""Typed production qualification ports for deployment-specific guarantees."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel.canonical import canonical_digest, require_sha256


class QualificationKind(StrEnum):
    CONSENSUS = "consensus"
    WORKER_ATTESTATION = "worker_attestation"
    ISOLATION = "isolation"


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    kind: QualificationKind
    provider_id: str
    provider_version: str
    evidence_digest: str
    constraints: tuple[str, ...] = ()
    qualification_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, QualificationKind):
            raise TypeError("qualification kind must be typed")
        if type(self.provider_id) is not str or not self.provider_id.strip():
            raise ValueError("qualification provider_id is required")
        if type(self.provider_version) is not str or not self.provider_version.strip():
            raise ValueError("qualification provider_version is required")
        require_sha256(self.evidence_digest, "qualification evidence_digest")
        if type(self.constraints) is not tuple or any(
            type(item) is not str or not item.strip() for item in self.constraints
        ):
            raise TypeError("qualification constraints must be text tuple")
        object.__setattr__(
            self, "qualification_digest",
            canonical_digest({
                "kind": self.kind.value,
                "provider_id": self.provider_id,
                "provider_version": self.provider_version,
                "evidence_digest": self.evidence_digest,
                "constraints": self.constraints,
            }),
        )


@runtime_checkable
class ConsensusQualificationPort(Protocol):
    def qualify_consensus(self, machine_id: str) -> QualificationEvidence: ...


@runtime_checkable
class WorkerAttestationQualificationPort(Protocol):
    def qualify_worker_attestation(self, worker_id: str) -> QualificationEvidence: ...


@runtime_checkable
class IsolationQualificationPort(Protocol):
    def qualify_isolation(self, workload_id: str) -> QualificationEvidence: ...


@runtime_checkable
class ExecutionQualificationPort(Protocol):
    def qualify(self, machine_id: str, worker_id: str, workload_id: str) -> tuple[QualificationEvidence, ...]: ...


def require_production_qualification(
    port: ExecutionQualificationPort,
    *,
    machine_id: str,
    worker_id: str,
    workload_id: str,
) -> tuple[QualificationEvidence, ...]:
    if not isinstance(port, ExecutionQualificationPort):
        raise TypeError("execution qualification must implement typed provider port")
    evidence = port.qualify(machine_id, worker_id, workload_id)
    if type(evidence) is not tuple or not evidence:
        raise ValueError("production qualification must return evidence")
    if any(not isinstance(item, QualificationEvidence) for item in evidence):
        raise TypeError("production qualification must return typed evidence")
    if len({item.qualification_digest for item in evidence}) != len(evidence):
        raise ValueError("production qualification evidence must be unique")
    kinds = tuple(item.kind for item in evidence)
    if set(kinds) != set(QualificationKind):
        raise ValueError("production qualification must cover consensus, attestation and isolation")
    return evidence


__all__ = [
    "ConsensusQualificationPort",
    "ExecutionQualificationPort",
    "IsolationQualificationPort",
    "QualificationEvidence",
    "QualificationKind",
    "WorkerAttestationQualificationPort",
    "require_production_qualification",
]
