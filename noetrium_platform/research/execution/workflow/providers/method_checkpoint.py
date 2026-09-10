"""Crash-durable JSON checkpoint provider for the universal method machine."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from typing import Any

from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt, thaw_json

from ..api.method_machine import (
    MethodCheckpoint,
    MethodCheckpointStorePort,
    MethodEvent,
    MethodEvidenceStatus,
)


def _receipt_to_dict(receipt: EffectReceipt) -> dict[str, object]:
    return {
        "effect_id": receipt.effect_id,
        "request_digest": receipt.request_digest,
        "effect_class": receipt.effect_class.value,
        "certainty": receipt.certainty.value,
        "provider_instance_id": receipt.provider_instance_id,
        "verification_required": receipt.verification_required,
        "before_artifact": thaw_json(receipt.before_artifact),
        "after_artifact": thaw_json(receipt.after_artifact),
        "provider_receipt": thaw_json(receipt.provider_receipt),
    }


def _receipt_from_dict(value: dict[str, Any]) -> EffectReceipt:
    return EffectReceipt(
        effect_id=value["effect_id"],
        request_digest=value["request_digest"],
        effect_class=EffectClass(value["effect_class"]),
        certainty=EffectCertainty(value["certainty"]),
        provider_instance_id=value.get("provider_instance_id"),
        verification_required=bool(value.get("verification_required", False)),
        before_artifact=value.get("before_artifact"),
        after_artifact=value.get("after_artifact"),
        provider_receipt=value.get("provider_receipt"),
    )


class JsonMethodCheckpointStore(MethodCheckpointStorePort):
    """Atomic, monotonic, content-addressed checkpoint files.

    The provider stores only frozen JSON envelopes.  It is deliberately small
    and provider-neutral; durable evidence and external-effect reconciliation
    remain owned by their existing authorities.
    """

    durability = "crash_durable_file"
    schema_version = "method-checkpoint.v2"

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _path(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not run_id.strip() or any(char in run_id for char in "/\\\0"):
            raise ValueError("method checkpoint run_id is invalid")
        return self._root / f"{run_id}.json"

    @staticmethod
    def _encode(checkpoint: MethodCheckpoint) -> dict[str, object]:
        return {
            "schema_version": JsonMethodCheckpointStore.schema_version,
            "run_id": checkpoint.run_id,
            "program_digest": checkpoint.program_digest,
            "sequence": checkpoint.sequence,
            "current_node": checkpoint.current_node,
            "state": thaw_json(checkpoint.state),
            "previous_value": thaw_json(checkpoint.previous_value),
            "next_node": checkpoint.next_node,
            "visit_counts": [[node_id, count] for node_id, count in checkpoint.visit_counts],
            "events": [{"kind": event.kind, "payload": thaw_json(event.payload)} for event in checkpoint.events],
            "binding_plan_digest": checkpoint.binding_plan_digest,
            "runtime_binding_digest": checkpoint.runtime_binding_digest,
            "schema_digest": checkpoint.schema_digest,
            "effect_receipts": [_receipt_to_dict(receipt) for receipt in checkpoint.effect_receipts],
            "evidence_status": checkpoint.evidence_status.value,
            "checkpoint_id": checkpoint.checkpoint_id,
        }

    @staticmethod
    def _decode(value: dict[str, Any]) -> MethodCheckpoint:
        if value.get("schema_version") != JsonMethodCheckpointStore.schema_version:
            raise ValueError("unsupported method checkpoint schema")
        checkpoint = MethodCheckpoint(
            run_id=value["run_id"],
            program_digest=value["program_digest"],
            sequence=value["sequence"],
            current_node=value["current_node"],
            state=value["state"],
            previous_value=value.get("previous_value"),
            next_node=value.get("next_node"),
            visit_counts=tuple((item[0], item[1]) for item in value.get("visit_counts", [])),
            events=tuple(MethodEvent(item["kind"], item.get("payload")) for item in value.get("events", [])),
            binding_plan_digest=value.get("binding_plan_digest"),
            runtime_binding_digest=value.get("runtime_binding_digest"),
            schema_digest=value.get("schema_digest"),
            effect_receipts=tuple(_receipt_from_dict(item) for item in value.get("effect_receipts", [])),
            evidence_status=MethodEvidenceStatus(value.get("evidence_status", MethodEvidenceStatus.UNKNOWN.value)),
        )
        if value.get("checkpoint_id") != checkpoint.checkpoint_id:
            raise ValueError("method checkpoint content digest mismatch")
        return checkpoint

    def save(self, checkpoint: MethodCheckpoint) -> None:
        if not isinstance(checkpoint, MethodCheckpoint):
            raise TypeError("method checkpoint store accepts MethodCheckpoint")
        path = self._path(checkpoint.run_id)
        with self._lock:
            previous = self.load(checkpoint.run_id)
            if previous is not None:
                if checkpoint.sequence < previous.sequence:
                    raise ValueError("method checkpoint sequence moved backwards")
                if checkpoint.sequence == previous.sequence and checkpoint.checkpoint_id != previous.checkpoint_id:
                    raise ValueError("method checkpoint sequence has conflicting content")
                if checkpoint.checkpoint_id == previous.checkpoint_id:
                    return
            temporary = path.with_suffix(path.suffix + ".tmp")
            with temporary.open("w", encoding="utf-8") as stream:
                stream.write(json.dumps(self._encode(checkpoint), sort_keys=True, separators=(",", ":"), ensure_ascii=False))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
            directory_flag = getattr(os, "O_DIRECTORY", 0)
            if directory_flag:
                directory_fd = os.open(self._root, os.O_RDONLY | directory_flag)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)

    def load(self, run_id: str) -> MethodCheckpoint | None:
        path = self._path(run_id)
        with self._lock:
            if not path.exists():
                return None
            return self._decode(json.loads(path.read_text(encoding="utf-8")))


__all__ = ["JsonMethodCheckpointStore"]
