from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)
from noetrium_platform.substrate.api import (
    DirectoryLayoutPort,
    FileCausalEventStore,
    ManagedDirectoryKind,
)

from .applied import AppliedModelDeployment
from .codec import decode_applied, encode_applied


_APPLIED_PROJECTION_SCHEMA = "noetrium.model-applied-projection.v3"


@dataclass(frozen=True, slots=True)
class _AppliedProjection:
    active: AppliedModelDeployment | None
    cleared: tuple[AppliedModelDeployment, ...]


def _applied_data(value: AppliedModelDeployment) -> dict[str, object]:
    decoded = json.loads(encode_applied(value).decode("utf-8"))
    if not isinstance(decoded, dict):
        raise RuntimeError("applied model codec did not produce an object")
    return decoded


def _encode_projection(value: _AppliedProjection) -> bytes:
    return json.dumps(
        {
            "schema": _APPLIED_PROJECTION_SCHEMA,
            "active": None if value.active is None else _applied_data(value.active),
            "cleared": [_applied_data(row) for row in value.cleared],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _decode_projection(raw: bytes, *, deployment_id: str) -> _AppliedProjection:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("model applied projection is unreadable") from exc
    if not isinstance(document, dict) or set(document) != {"schema", "active", "cleared"}:
        raise RuntimeError("model applied projection shape is invalid")
    if document.get("schema") != _APPLIED_PROJECTION_SCHEMA:
        raise RuntimeError("model applied projection schema is unsupported")
    active_raw = document.get("active")
    active = None
    if active_raw is not None:
        if not isinstance(active_raw, dict):
            raise RuntimeError("model applied active projection must be an object")
        active = decode_applied(active_raw)
    cleared_raw = document.get("cleared")
    if not isinstance(cleared_raw, list) or any(
        not isinstance(row, dict) for row in cleared_raw
    ):
        raise RuntimeError("model applied cleared projection must be object list")
    cleared = tuple(decode_applied(row) for row in cleared_raw)
    rows = (() if active is None else (active,)) + cleared
    if any(row.desired_deployment.deployment_id != deployment_id for row in rows):
        raise RuntimeError("model applied projection crossed deployment identity")
    cleared_digests = tuple(row.runtime_digest for row in cleared)
    if len(cleared_digests) != len(set(cleared_digests)):
        raise RuntimeError("model applied projection duplicates cleared generation")
    if active is not None and active.runtime_digest in set(cleared_digests):
        raise RuntimeError("model applied projection marks one generation active and cleared")
    return _AppliedProjection(active, cleared)


class AppliedModelDeploymentStore:
    """Causal Event projection of model control-plane applied generations.

    Physical ownership/liveness is never decided here; UniversalResourceAuthority
    owns that truth.  This store records only the model controller's observed
    active/cleared generation history.  The JSON file is disposable and must be
    exactly rebuildable from the injected causal Event journal.
    """

    def __init__(
        self,
        directories: DirectoryLayoutPort,
    ) -> None:
        state = directories.root(ManagedDirectoryKind.STATE)
        self._root = state / "model" / "deployments" / "applied-projections-v3"
        self._lock_root = (
            directories.root(ManagedDirectoryKind.LOCKS)
            / "model-applied-projection"
        )
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock_root.mkdir(parents=True, exist_ok=True)
        # Bounded derived handles retain validated Event prefixes; they do not
        # own deployment truth, which remains in the durable causal journal.
        self._journal_handles = lru_cache(maxsize=128)(self._new_journal)

    @staticmethod
    def _key(deployment_id: str) -> str:
        return canonical_digest({"deployment_id": deployment_id})

    def _path(self, deployment_id: str) -> Path:
        return self._root / f"{deployment_id}.json"

    def _lock_path(self, deployment_id: str) -> Path:
        return self._lock_root / f"{self._key(deployment_id)}.lock"

    def _journal(self, deployment_id: str) -> FileCausalEventStore:
        return self._journal_handles(deployment_id)

    def _new_journal(self, deployment_id: str) -> FileCausalEventStore:
        return FileCausalEventStore(
            self._path(deployment_id),
            state_schema=_APPLIED_PROJECTION_SCHEMA,
            authority_domain="model.applied." + self._key(deployment_id),
        )

    def _read_projection(self, deployment_id: str) -> _AppliedProjection:
        journal = self._journal(deployment_id)
        try:
            payload = journal.read()
        except FileNotFoundError:
            return _AppliedProjection(None, ())
        return _decode_projection(payload, deployment_id=deployment_id)

    def _append_projection(
        self,
        deployment_id: str,
        projection: _AppliedProjection,
        *,
        phase: str,
    ) -> None:
        self._journal(deployment_id).append(
            _encode_projection(projection),
            phase=phase,
        )

    @staticmethod
    def _validate_runtime_digest(value: str) -> None:
        if (
            type(value) is not str
            or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)
        ):
            raise ValueError(
                "applied model runtime digest must be lowercase SHA-256"
            )

    def put(self, value: AppliedModelDeployment) -> AppliedModelDeployment:
        deployment_id = value.desired_deployment.deployment_id
        self._validate_id(deployment_id)
        runtime_digest = value.runtime_digest
        self._validate_runtime_digest(runtime_digest)
        with InterprocessFileLock(self._lock_path(deployment_id)):
            projection = self._read_projection(deployment_id)
            if any(row.runtime_digest == runtime_digest for row in projection.cleared):
                raise RuntimeError(
                    "cleared model process generation cannot be resurrected: "
                    + deployment_id
                )
            current = projection.active
            if current is not None:
                if current.runtime_digest == runtime_digest:
                    if current != value:
                        raise RuntimeError(
                            "same model applied runtime digest has different payload: "
                            + deployment_id
                        )
                    return current
                raise RuntimeError(
                    "refusing to replace an observed live model generation: "
                    + deployment_id
                )
            self._append_projection(
                deployment_id,
                _AppliedProjection(value, projection.cleared),
                phase="model-applied",
            )
            return value

    def read(self, deployment_id: str) -> AppliedModelDeployment | None:
        self._validate_id(deployment_id)
        with InterprocessFileLock(self._lock_path(deployment_id)):
            return self._read_projection(deployment_id).active

    def cleared_snapshots(
        self,
        deployment_id: str,
    ) -> tuple[AppliedModelDeployment, ...]:
        self._validate_id(deployment_id)
        with InterprocessFileLock(self._lock_path(deployment_id)):
            return self._read_projection(deployment_id).cleared

    def clear(
        self,
        deployment_id: str,
        *,
        expected_runtime_digest: str,
    ) -> bool:
        self._validate_id(deployment_id)
        self._validate_runtime_digest(expected_runtime_digest)
        with InterprocessFileLock(self._lock_path(deployment_id)):
            projection = self._read_projection(deployment_id)
            current = projection.active
            if current is None:
                return any(
                    row.runtime_digest == expected_runtime_digest
                    for row in projection.cleared
                )
            if current.runtime_digest != expected_runtime_digest:
                raise RuntimeError(
                    "stale model applied clear generation: " + deployment_id
                )
            cleared = projection.cleared
            if all(row.runtime_digest != current.runtime_digest for row in cleared):
                cleared = tuple((*cleared, current))
            self._append_projection(
                deployment_id,
                _AppliedProjection(None, cleared),
                phase="model-cleared",
            )
            return True

    def purge_cleared_after_retirement(self, deployment_id: str) -> int:
        """Compact the latest projection after permanent logical retirement.

        Historical cleared generations remain immutable in prior Event Units;
        only the disposable latest projection drops them.
        """

        self._validate_id(deployment_id)
        with InterprocessFileLock(self._lock_path(deployment_id)):
            projection = self._read_projection(deployment_id)
            if projection.active is not None:
                raise RuntimeError(
                    "cannot purge model cleared projection while an active generation remains: "
                    + deployment_id
                )
            removed = len(projection.cleared)
            if removed:
                self._append_projection(
                    deployment_id,
                    _AppliedProjection(None, ()),
                    phase="model-retired-projection-compacted",
                )
            return removed

    def verify_projection_rebuild(self, deployment_id: str) -> _AppliedProjection:
        self._validate_id(deployment_id)
        with InterprocessFileLock(self._lock_path(deployment_id)):
            payload = self._journal(deployment_id).verify_projection_rebuild()
            if not payload:
                return _AppliedProjection(None, ())
            return _decode_projection(payload, deployment_id=deployment_id)

    @staticmethod
    def _validate_id(value: str) -> None:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("invalid applied deployment id")


__all__ = ["AppliedModelDeploymentStore"]
