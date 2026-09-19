from __future__ import annotations

import json
from dataclasses import asdict

from noetrium_platform.capabilities.participant.core.api.checkpoint import ParticipantCheckpointRef

from ..api.contracts import (
    RunCheckpointIntegrityError,
    RunCheckpointManifest,
    RunParticipantSnapshotRef,
)

_ENVELOPE_FIELDS = {"manifest", "manifest_digest"}
_MANIFEST_FIELDS = {
    "checkpoint_id", "schema_version", "experiment_spec_digest", "run_id",
    "session_id", "decision_cycle_id", "cycle_identity_digest", "participant_snapshots",
}
_SNAPSHOT_FIELDS = {"checkpoint", "generation"}
_CHECKPOINT_FIELDS = {
    "role", "runtime_binding_digest", "component_digest", "session_id", "payload_sha256",
}


def _require_exact_object(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise TypeError(f"{label} fields are not exact")
    return value


def _require_string(value: object, label: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be a string")
    return value


def _decode_participant_ref(value: object) -> ParticipantCheckpointRef:
    row = _require_exact_object(value, _CHECKPOINT_FIELDS, "participant checkpoint ref")
    return ParticipantCheckpointRef(
        role=_require_string(row["role"], "participant role"),
        runtime_binding_digest=_require_string(
            row["runtime_binding_digest"], "runtime_binding_digest"
        ),
        component_digest=_require_string(row["component_digest"], "component_digest"),
        session_id=_require_string(row["session_id"], "participant session_id"),
        payload_sha256=_require_string(row["payload_sha256"], "participant payload_sha256"),
    )


def _decode_snapshot(value: object) -> RunParticipantSnapshotRef:
    row = _require_exact_object(value, _SNAPSHOT_FIELDS, "participant snapshot")
    generation = row["generation"]
    if generation is not None and type(generation) is not str:
        raise TypeError("participant generation must be a string or null")
    return RunParticipantSnapshotRef(
        _decode_participant_ref(row["checkpoint"]),
        generation,
    )


def _decode_manifest(value: object) -> RunCheckpointManifest:
    raw = _require_exact_object(value, _MANIFEST_FIELDS, "checkpoint manifest")
    snapshots_raw = raw["participant_snapshots"]
    if not isinstance(snapshots_raw, list):
        raise TypeError("participant_snapshots must be a list")
    values = {
        field: _require_string(raw[field], f"checkpoint {field}")
        for field in _MANIFEST_FIELDS - {"participant_snapshots"}
    }
    return RunCheckpointManifest(
        **values,
        participant_snapshots=tuple(_decode_snapshot(item) for item in snapshots_raw),
    )


class RunCheckpointManifestCodec:
    """Strict document codec; owns no filesystem or checkpoint lifecycle authority."""

    @staticmethod
    def encode(manifest: RunCheckpointManifest) -> bytes:
        envelope = {"manifest": asdict(manifest), "manifest_digest": manifest.digest()}
        return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def decode(payload: bytes) -> RunCheckpointManifest:
        try:
            if type(payload) is not bytes:
                raise TypeError("study checkpoint manifest payload must be bytes")
            document = json.loads(payload.decode("utf-8"))
            envelope = _require_exact_object(document, _ENVELOPE_FIELDS, "checkpoint envelope")
            expected = _require_string(envelope["manifest_digest"], "checkpoint manifest digest")
            manifest = _decode_manifest(envelope["manifest"])
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise RunCheckpointIntegrityError(
                "invalid study checkpoint manifest document"
            ) from exc
        if manifest.digest() != expected:
            raise RunCheckpointIntegrityError("study checkpoint manifest digest mismatch")
        if payload != RunCheckpointManifestCodec.encode(manifest):
            raise RunCheckpointIntegrityError(
                "study checkpoint manifest bytes are not canonical JSON"
            )
        return manifest


__all__ = ["RunCheckpointManifestCodec"]
