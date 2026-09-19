from __future__ import annotations

import json

from noetrium_platform.foundation.kernel.kernel import canonical_bytes

from ..api import (
    RunCheckpointIntegrityError,
    WorkloadCheckpointComponentRef,
    WorkloadCheckpointManifest,
    WorkloadExecutionCut,
)

_ENVELOPE_FIELDS = {"manifest", "manifest_digest"}
_MANIFEST_FIELDS = {
    "checkpoint_id", "schema_version", "run_id", "study_id", "workload_id",
    "branch_id", "source_cut_id", "environment_generation", "method_generation",
    "task_manifest_digest", "checkpoint_compatibility_digest", "execution_cut", "execution_cut_digest", "component_refs",
}
_CUT_FIELDS = {"completed_task_ids", "current_task_id", "decision_cycle_id", "status"}
_REF_FIELDS = {"component_id", "codec_id", "schema_version", "payload_sha256", "payload_size"}


def _require_exact_object(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise TypeError(f"{label} fields are not exact")
    return value


def _require_string(value: object, label: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be a string")
    return value


def _decode_execution_cut(value: object) -> WorkloadExecutionCut:
    raw = _require_exact_object(value, _CUT_FIELDS, "execution cut")
    completed = raw["completed_task_ids"]
    if not isinstance(completed, list) or any(type(item) is not str for item in completed):
        raise TypeError("execution cut completed_task_ids must be a string list")
    current = raw["current_task_id"]
    cycle = raw["decision_cycle_id"]
    if current is not None and type(current) is not str:
        raise TypeError("execution cut current_task_id must be string or null")
    if cycle is not None and type(cycle) is not str:
        raise TypeError("execution cut decision_cycle_id must be string or null")
    return WorkloadExecutionCut(
        tuple(completed),
        current,
        cycle,
        _require_string(raw["status"], "execution cut status"),
    )


def _decode_component_ref(value: object) -> WorkloadCheckpointComponentRef:
    row = _require_exact_object(value, _REF_FIELDS, "checkpoint component ref")
    payload_size = row["payload_size"]
    if type(payload_size) is not int:
        raise TypeError("checkpoint component payload_size must be an integer")
    return WorkloadCheckpointComponentRef(
        component_id=_require_string(row["component_id"], "component_id"),
        codec_id=_require_string(row["codec_id"], "codec_id"),
        schema_version=_require_string(row["schema_version"], "component schema_version"),
        payload_sha256=_require_string(row["payload_sha256"], "payload_sha256"),
        payload_size=payload_size,
    )


def _decode_manifest(value: object) -> WorkloadCheckpointManifest:
    raw = _require_exact_object(value, _MANIFEST_FIELDS, "checkpoint manifest")
    refs_raw = raw["component_refs"]
    if not isinstance(refs_raw, list):
        raise TypeError("checkpoint component_refs must be a list")
    values = {
        field: _require_string(raw[field], f"checkpoint {field}")
        for field in _MANIFEST_FIELDS - {"execution_cut", "component_refs"}
    }
    return WorkloadCheckpointManifest(
        **values,
        execution_cut=_decode_execution_cut(raw["execution_cut"]),
        component_refs=tuple(_decode_component_ref(item) for item in refs_raw),
    )


class WorkloadCheckpointManifestCodec:
    """Strict codec for the workload checkpoint manifest document."""

    @staticmethod
    def encode(manifest: WorkloadCheckpointManifest) -> bytes:
        return canonical_bytes({"manifest": manifest, "manifest_digest": manifest.digest()})

    @staticmethod
    def decode(payload: bytes) -> WorkloadCheckpointManifest:
        try:
            if type(payload) is not bytes:
                raise TypeError("workload checkpoint manifest payload must be bytes")
            document = json.loads(payload.decode("utf-8"))
            envelope = _require_exact_object(document, _ENVELOPE_FIELDS, "checkpoint envelope")
            expected = _require_string(envelope["manifest_digest"], "checkpoint manifest digest")
            manifest = _decode_manifest(envelope["manifest"])
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise RunCheckpointIntegrityError(
                "invalid workload checkpoint manifest document"
            ) from exc
        if manifest.digest() != expected:
            raise RunCheckpointIntegrityError("workload checkpoint manifest digest mismatch")
        return manifest


__all__ = ["WorkloadCheckpointManifestCodec"]
