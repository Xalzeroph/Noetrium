from __future__ import annotations

from dataclasses import asdict
import hashlib
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import canonical_bytes, canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    atomic_replace_bytes,
)

from ..api import (
    MethodCheckpoint,
    MethodEvidenceStatus,
    MethodRunResult,
)
from ..api.runtime_services import MethodEvidenceFactoryPort


class DirectoryEventMethodEvidence:
    """Durable Method evidence whose obligations are satisfied by same-id events."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        (self.root / "checkpoints").mkdir(parents=True, exist_ok=True)
        (self.root / "results").mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def record_checkpoint(self, checkpoint: MethodCheckpoint) -> None:
        if not isinstance(checkpoint, MethodCheckpoint):
            raise TypeError("method evidence checkpoint must be typed")
        payload = {
            "schema": "noetrium.method-evidence.checkpoint.v1",
            "checkpoint_id": checkpoint.checkpoint_id,
            "run_id": checkpoint.run_id,
            "program_digest": checkpoint.program_digest,
            "sequence": checkpoint.sequence,
            "current_node": checkpoint.current_node,
            "machine_id": checkpoint.machine_id,
            "machine_revision": checkpoint.machine_revision,
            "machine_commit_id": checkpoint.machine_commit_id,
            "state_digest": checkpoint.state_digest,
            "checkpoint_value": checkpoint.checkpoint_value,
        }
        atomic_replace_bytes(
            self.root / "checkpoints" / f"{checkpoint.checkpoint_id}.json",
            canonical_bytes(payload),
        )

    def record_result(self, result: MethodRunResult) -> None:
        if not isinstance(result, MethodRunResult):
            raise TypeError("method evidence result must be typed")
        payload = {
            "schema": "noetrium.method-evidence.result.v1",
            "run_id": result.run_id,
            "run_digest": result.run_digest,
            "status": result.status.value,
            "program_digest": result.program_digest,
            "value": result.value,
            "state": result.state,
            "events": tuple(
                {"kind": event.kind, "payload": event.payload}
                for event in result.events
            ),
            "effect_receipts": tuple(asdict(receipt) for receipt in result.effect_receipts),
            "step_count": result.step_count,
            "visit_counts": result.visit_counts,
            "evidence_status": result.evidence_status.value,
            "failure_code": result.failure_code,
            "failure_phase": result.failure_phase,
        }
        atomic_replace_bytes(
            self.root / "results" / f"{self._safe(result.run_id)}.json",
            canonical_bytes(payload),
        )

    def validate_result(
        self,
        result: MethodRunResult,
        obligations: tuple[str, ...],
    ) -> MethodEvidenceStatus:
        if not isinstance(result, MethodRunResult):
            raise TypeError("method evidence result must be typed")
        if not isinstance(obligations, tuple):
            raise TypeError("method evidence obligations must be a tuple")
        event_kinds = {event.kind for event in result.events}
        return (
            MethodEvidenceStatus.COMPLETE
            if all(obligation in event_kinds for obligation in obligations)
            else MethodEvidenceStatus.INCOMPLETE
        )


class DirectoryMethodEvidenceFactory(MethodEvidenceFactoryPort):
    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "provider": "directory-method-evidence",
            "version": 1,
        })

    def create(self, root: str | Path) -> DirectoryEventMethodEvidence:
        return DirectoryEventMethodEvidence(root)


__all__ = ["DirectoryEventMethodEvidence", "DirectoryMethodEvidenceFactory"]
