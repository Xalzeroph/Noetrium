from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

from noetrium_platform.capabilities.model.serving.api import RuntimeCanaryEvidence
from noetrium_platform.foundation.kernel.kernel.durability import (
    ChecksummedDocumentError,
    decode_checksummed_document,
    encode_checksummed_document,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import InterprocessFileLock


_SCHEMA = "runtime-canary-evidence.v3"
_FIELDS = frozenset({
    "deployment_id", "deployment_generation", "route_digest", "role", "canary_id",
    "suite_digest", "process_pid", "process_start_marker", "argv_digest",
    "request_digest", "probe_digest", "response_digest", "contract_digest", "passed", "observed_at",
    "evidence_digest",
})
_LOCAL_LOCKS_GUARD = Lock()
_LOCAL_LOCKS: dict[str, Lock] = {}


class RuntimeCanaryEvidenceError(RuntimeError):
    pass


def _digest(value: object, field: str) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise RuntimeCanaryEvidenceError(f"{field} must be lowercase SHA-256")
    return value

def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise RuntimeCanaryEvidenceError(f"{field} must be non-empty text")
    return value


def _local_lock(path: Path) -> Lock:
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _LOCAL_LOCKS_GUARD:
        lock = _LOCAL_LOCKS.get(key)
        if lock is None:
            lock = Lock()
            _LOCAL_LOCKS[key] = lock
        return lock


def _encode(evidence: RuntimeCanaryEvidence, runtime_manifest_digest: str) -> bytes:
    payload = {
        "runtime_manifest_digest": _digest(runtime_manifest_digest, "runtime_manifest_digest"),
        "evidence": {
        "deployment_id": evidence.deployment_id,
        "deployment_generation": evidence.deployment_generation,
        "route_digest": evidence.route_digest,
        "role": evidence.role,
        "canary_id": evidence.canary_id,
        "suite_digest": evidence.suite_digest,
        "process_pid": evidence.process_pid,
        "process_start_marker": evidence.process_start_marker,
        "argv_digest": evidence.argv_digest,
        "request_digest": evidence.request_digest,
        "probe_digest": evidence.probe_digest,
        "response_digest": evidence.response_digest,
        "contract_digest": evidence.contract_digest,
        "passed": evidence.passed,
        "observed_at": evidence.observed_at,
        "evidence_digest": evidence.evidence_digest,
        },
    }
    return encode_checksummed_document(_SCHEMA, payload)


def _decode(
    raw: bytes,
    *,
    expected_runtime_manifest_digest: str | None = None,
) -> RuntimeCanaryEvidence:
    try:
        payload = decode_checksummed_document(raw, expected_schema=_SCHEMA).payload
    except ChecksummedDocumentError as exc:
        raise RuntimeCanaryEvidenceError("runtime canary document integrity failure") from exc
    if type(payload) is not dict or frozenset(payload) != frozenset({"runtime_manifest_digest", "evidence"}):
        raise RuntimeCanaryEvidenceError("runtime canary payload field set mismatch")
    manifest = _digest(payload["runtime_manifest_digest"], "runtime_manifest_digest")
    if expected_runtime_manifest_digest is not None:
        expected = _digest(expected_runtime_manifest_digest, "expected_runtime_manifest_digest")
        if manifest != expected:
            raise RuntimeCanaryEvidenceError("runtime canary runtime manifest binding mismatch")
    value = payload["evidence"]
    if type(value) is not dict or frozenset(value) != _FIELDS:
        raise RuntimeCanaryEvidenceError("runtime canary evidence field set mismatch")
    if type(value["process_pid"]) is not int or value["process_pid"] <= 0:
        raise RuntimeCanaryEvidenceError("runtime canary process_pid must be positive integer")
    if type(value["passed"]) is not bool:
        raise RuntimeCanaryEvidenceError("runtime canary passed must be bool")
    if type(value["observed_at"]) is not float:
        raise RuntimeCanaryEvidenceError("runtime canary observed_at must be JSON float")
    try:
        return RuntimeCanaryEvidence(
            deployment_id=_text(value["deployment_id"], "deployment_id"),
            deployment_generation=_digest(value["deployment_generation"], "deployment_generation"),
            route_digest=_digest(value["route_digest"], "route_digest"),
            role=_text(value["role"], "role"),
            canary_id=_text(value["canary_id"], "canary_id"),
            suite_digest=_digest(value["suite_digest"], "suite_digest"),
            process_pid=value["process_pid"],
            process_start_marker=_text(value["process_start_marker"], "process_start_marker"),
            argv_digest=_digest(value["argv_digest"], "argv_digest"),
            request_digest=_digest(value["request_digest"], "request_digest"),
            probe_digest=_digest(value["probe_digest"], "probe_digest"),
            response_digest=_digest(value["response_digest"], "response_digest"),
            contract_digest=_digest(value["contract_digest"], "contract_digest"),
            passed=value["passed"],
            observed_at=value["observed_at"],
            evidence_digest=_digest(value["evidence_digest"], "evidence_digest"),
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeCanaryEvidenceError("runtime canary evidence is invalid") from exc


class DirectoryRuntimeCanaryEvidenceStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, runtime_manifest_digest: str, evidence_digest: str) -> Path:
        manifest = _digest(runtime_manifest_digest, "runtime_manifest_digest")
        evidence = _digest(evidence_digest, "evidence_digest")
        return self.root / manifest / f"{evidence}.json"

    def publish(self, runtime_manifest_digest: str, evidence: RuntimeCanaryEvidence) -> str:
        path = self._path(runtime_manifest_digest, evidence.evidence_digest)
        lock_path = path.with_name(path.name + ".lock")
        raw = _encode(evidence, runtime_manifest_digest)
        with _local_lock(lock_path), InterprocessFileLock(lock_path):
            if path.exists():
                existing = _decode(
                    path.read_bytes(),
                    expected_runtime_manifest_digest=runtime_manifest_digest,
                )
                if existing != evidence:
                    raise RuntimeCanaryEvidenceError(
                        "runtime canary evidence digest already exists with different content"
                    )
                return str(path)
            atomic_replace_bytes(path, raw)
            persisted = _decode(
                path.read_bytes(),
                expected_runtime_manifest_digest=runtime_manifest_digest,
            )
            if persisted != evidence:
                raise RuntimeCanaryEvidenceError("runtime canary evidence readback drift")
            return str(path)

    def load(
        self,
        runtime_manifest_digest: str,
        evidence_digest: str,
    ) -> RuntimeCanaryEvidence:
        path = self._path(runtime_manifest_digest, evidence_digest)
        try:
            evidence = _decode(
                path.read_bytes(),
                expected_runtime_manifest_digest=runtime_manifest_digest,
            )
        except OSError as exc:
            raise RuntimeCanaryEvidenceError(
                f"runtime canary evidence cannot be read: {path}"
            ) from exc
        if evidence.evidence_digest != evidence_digest:
            raise RuntimeCanaryEvidenceError("runtime canary evidence identity drift")
        return evidence


__all__ = [
    "DirectoryRuntimeCanaryEvidenceStore",
    "RuntimeCanaryEvidenceError",
]
