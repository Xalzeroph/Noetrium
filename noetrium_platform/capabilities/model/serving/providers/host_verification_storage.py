from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
import re
from threading import Lock

from noetrium_platform.foundation.kernel.kernel.durability import (
    ChecksummedDocumentError,
    decode_checksummed_document,
    encode_checksummed_document,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import InterprocessFileLock

from ..api.host_verification import HostInventoryReceipt, HostResourceDelta
from ..api.inventory import RuntimeInventory

_SCHEMA = "host-inventory-evidence.v2"
_DELTA_SCHEMA = "host-resource-delta-evidence.v2"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PHASE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_RECEIPT_FIELDS = frozenset({
    "schema_version", "phase", "host_identity_digest", "snapshot_digest",
    "captured_at_unix", "effective_available_memory_bytes", "gpu_free_memory_bytes",
    "listening_ports", "mount_free_bytes", "runtime", "receipt_digest",
})
_DELTA_FIELDS = frozenset({
    "schema_version", "before_phase", "after_phase", "before_snapshot_digest",
    "after_snapshot_digest", "host_memory_delta_bytes", "gpu_free_memory_delta_bytes",
    "ports_added", "ports_removed", "mount_free_delta_bytes", "delta_digest",
})
_LOCAL_LOCKS_GUARD = Lock()
_LOCAL_LOCKS: dict[str, Lock] = {}


def _sha256(value: object, field: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be lowercase SHA-256")
    return value


def _phase(value: object, field: str = "phase") -> str:
    if type(value) is not str or _PHASE_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a stable token")
    return value


def _local_lock(path: Path) -> Lock:
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _LOCAL_LOCKS_GUARD:
        lock = _LOCAL_LOCKS.get(key)
        if lock is None:
            lock = Lock()
            _LOCAL_LOCKS[key] = lock
        return lock


def _pairs(value: object, field: str) -> tuple[tuple[object, object], ...]:
    if type(value) is not list:
        raise ValueError(f"{field} must be a JSON list")
    rows: list[tuple[object, object]] = []
    for row in value:
        if type(row) is not list or len(row) != 2:
            raise ValueError(f"{field} rows must be two-item JSON lists")
        rows.append((row[0], row[1]))
    return tuple(rows)


def _items(value: object, field: str) -> tuple[object, ...]:
    if type(value) is not list:
        raise ValueError(f"{field} must be a JSON list")
    return tuple(value)


def _encode_receipt(runtime_manifest_digest: str, receipt: HostInventoryReceipt) -> bytes:
    return encode_checksummed_document(
        _SCHEMA,
        {
            "runtime_manifest_digest": runtime_manifest_digest,
            "receipt": asdict(receipt),
        },
    )


def _decode_receipt(
    raw: bytes,
    *,
    runtime_manifest_digest: str,
    phase: str,
) -> HostInventoryReceipt:
    try:
        payload = decode_checksummed_document(raw, expected_schema=_SCHEMA).payload
    except ChecksummedDocumentError as exc:
        raise ValueError("host inventory evidence integrity failure") from exc
    if type(payload) is not dict or frozenset(payload) != frozenset({"runtime_manifest_digest", "receipt"}):
        raise ValueError("host inventory evidence payload field set mismatch")
    manifest = _sha256(payload["runtime_manifest_digest"], "runtime_manifest_digest")
    expected_manifest = _sha256(runtime_manifest_digest, "runtime_manifest_digest")
    if manifest != expected_manifest:
        raise ValueError("host inventory evidence runtime manifest binding mismatch")
    expected_phase = _phase(phase)
    value = payload["receipt"]
    if type(value) is not dict or frozenset(value) != _RECEIPT_FIELDS:
        raise ValueError("host inventory receipt field set mismatch")
    runtime = value["runtime"]
    if type(runtime) is not dict or frozenset(runtime) != frozenset({
        "kernel", "python", "node", "java", "nvidia_driver",
        "cuda_driver_api", "nvml", "sglang", "vllm",
    }):
        raise ValueError("host inventory runtime field set mismatch")
    receipt = HostInventoryReceipt(
        schema_version=value["schema_version"],
        phase=value["phase"],
        host_identity_digest=value["host_identity_digest"],
        snapshot_digest=value["snapshot_digest"],
        captured_at_unix=value["captured_at_unix"],
        effective_available_memory_bytes=value["effective_available_memory_bytes"],
        gpu_free_memory_bytes=_pairs(value["gpu_free_memory_bytes"], "gpu_free_memory_bytes"),
        listening_ports=_items(value["listening_ports"], "listening_ports"),
        mount_free_bytes=_pairs(value["mount_free_bytes"], "mount_free_bytes"),
        runtime=RuntimeInventory(**runtime),
        receipt_digest=value["receipt_digest"],
    )
    if receipt.phase != expected_phase:
        raise ValueError("host inventory evidence phase binding mismatch")
    return receipt


def _encode_delta(runtime_manifest_digest: str, delta: HostResourceDelta) -> bytes:
    return encode_checksummed_document(
        _DELTA_SCHEMA,
        {
            "runtime_manifest_digest": runtime_manifest_digest,
            "delta": asdict(delta),
        },
    )


def _decode_delta(raw: bytes, *, runtime_manifest_digest: str) -> HostResourceDelta:
    try:
        payload = decode_checksummed_document(raw, expected_schema=_DELTA_SCHEMA).payload
    except ChecksummedDocumentError as exc:
        raise ValueError("host resource delta evidence integrity failure") from exc
    if type(payload) is not dict or frozenset(payload) != frozenset({"runtime_manifest_digest", "delta"}):
        raise ValueError("host resource delta evidence payload field set mismatch")
    manifest = _sha256(payload["runtime_manifest_digest"], "runtime_manifest_digest")
    expected_manifest = _sha256(runtime_manifest_digest, "runtime_manifest_digest")
    if manifest != expected_manifest:
        raise ValueError("host resource delta runtime manifest binding mismatch")
    value = payload["delta"]
    if type(value) is not dict or frozenset(value) != _DELTA_FIELDS:
        raise ValueError("host resource delta field set mismatch")
    return HostResourceDelta(
        schema_version=value["schema_version"],
        before_phase=value["before_phase"],
        after_phase=value["after_phase"],
        before_snapshot_digest=value["before_snapshot_digest"],
        after_snapshot_digest=value["after_snapshot_digest"],
        host_memory_delta_bytes=value["host_memory_delta_bytes"],
        gpu_free_memory_delta_bytes=_pairs(
            value["gpu_free_memory_delta_bytes"], "gpu_free_memory_delta_bytes"
        ),
        ports_added=_items(value["ports_added"], "ports_added"),
        ports_removed=_items(value["ports_removed"], "ports_removed"),
        mount_free_delta_bytes=_pairs(
            value["mount_free_delta_bytes"], "mount_free_delta_bytes"
        ),
        delta_digest=value["delta_digest"],
    )


class DirectoryHostInventoryEvidenceStore:
    """Immutable checksummed host inventory and resource-delta evidence."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, runtime_manifest_digest: str, phase: str) -> Path:
        manifest = _sha256(runtime_manifest_digest, "runtime_manifest_digest")
        stable_phase = _phase(phase)
        return self.root / f"{manifest}.{stable_phase}.host-inventory.json"

    def _delta_path(self, runtime_manifest_digest: str, delta: HostResourceDelta) -> Path:
        manifest = _sha256(runtime_manifest_digest, "runtime_manifest_digest")
        return self.root / (
            f"{manifest}.{delta.before_phase}-to-{delta.after_phase}.host-delta.json"
        )

    def publish(self, runtime_manifest_digest: str, receipt: HostInventoryReceipt) -> str:
        path = self._path(runtime_manifest_digest, receipt.phase)
        lock_path = path.with_name(path.name + ".lock")
        raw = _encode_receipt(runtime_manifest_digest, receipt)
        with _local_lock(lock_path), InterprocessFileLock(lock_path):
            if path.exists():
                existing = _decode_receipt(
                    path.read_bytes(),
                    runtime_manifest_digest=runtime_manifest_digest,
                    phase=receipt.phase,
                )
                if existing != receipt:
                    raise ValueError("host inventory evidence already exists with different content")
                return str(path)
            atomic_replace_bytes(path, raw)
            persisted = _decode_receipt(
                path.read_bytes(),
                runtime_manifest_digest=runtime_manifest_digest,
                phase=receipt.phase,
            )
            if persisted != receipt:
                raise ValueError("host inventory evidence readback drift")
            return str(path)

    def load(self, runtime_manifest_digest: str, phase: str) -> HostInventoryReceipt:
        path = self._path(runtime_manifest_digest, phase)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"host inventory evidence cannot be read: {path}") from exc
        return _decode_receipt(
            raw,
            runtime_manifest_digest=runtime_manifest_digest,
            phase=phase,
        )

    def publish_delta(self, runtime_manifest_digest: str, delta: HostResourceDelta) -> str:
        path = self._delta_path(runtime_manifest_digest, delta)
        lock_path = path.with_name(path.name + ".lock")
        raw = _encode_delta(runtime_manifest_digest, delta)
        with _local_lock(lock_path), InterprocessFileLock(lock_path):
            if path.exists():
                existing = _decode_delta(
                    path.read_bytes(),
                    runtime_manifest_digest=runtime_manifest_digest,
                )
                if existing != delta:
                    raise ValueError("host resource delta evidence already exists with different content")
                return str(path)
            atomic_replace_bytes(path, raw)
            persisted = _decode_delta(
                path.read_bytes(),
                runtime_manifest_digest=runtime_manifest_digest,
            )
            if persisted != delta:
                raise ValueError("host resource delta evidence readback drift")
            return str(path)


__all__ = ["DirectoryHostInventoryEvidenceStore"]
