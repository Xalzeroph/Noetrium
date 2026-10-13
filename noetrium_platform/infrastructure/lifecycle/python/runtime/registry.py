"""Event-backed metadata projection for managed Python environments.

Registry files are disposable latest-state projections. Logical resource
generation/fencing belongs exclusively to ResourceAuthorityPort.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from noetrium_platform.foundation.api import (
    DirectoryLayoutPort,
    ManagedDirectoryKind,
    scope_from_data,
    scope_to_data,
)
from noetrium_platform.foundation.kernel.kernel import canonical_bytes
from noetrium_platform.foundation.kernel.truth import TruthModality
from noetrium_platform.infrastructure.lifecycle.python.api import (
    ManagedPythonEnvironment,
    PythonEnvironmentOwnership,
    PythonEnvironmentState,
)
from noetrium_platform.foundation.kernel.event_store import (
    FileCausalEventStore,
)


_SCHEMA = "python.environment.registry.v2"


class PythonEnvironmentRegistry:
    """Disposable metadata projection over per-environment causal Event truth."""

    def __init__(self, directories: DirectoryLayoutPort) -> None:
        self._root = directories.root(ManagedDirectoryKind.STATE) / "python-environments"
        self._root.mkdir(parents=True, exist_ok=True)
        self._journal_handles = lru_cache(maxsize=128)(self._new_journal)

    @staticmethod
    def _validate_id(value: str) -> None:
        if (
            type(value) is not str
            or not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
        ):
            raise ValueError("invalid Python environment id")

    def _path(self, environment_id: str) -> Path:
        self._validate_id(environment_id)
        return self._root / f"{environment_id}.json"

    def _journal(self, environment_id: str) -> FileCausalEventStore:
        return self._journal_handles(environment_id)

    def _new_journal(self, environment_id: str) -> FileCausalEventStore:
        return FileCausalEventStore(
            self._path(environment_id),
            state_schema=_SCHEMA,
        )

    @staticmethod
    def _payload(value: ManagedPythonEnvironment, *, status: str) -> bytes:
        return canonical_bytes(
            {
                "schema": _SCHEMA,
                "status": status,
                "environment_id": value.environment_id,
                "scope": scope_to_data(value.scope),
                "backend": value.backend,
                "root": str(value.root),
                "python_path": str(value.python_path),
                "ownership": value.ownership.value,
                "description": value.description,
                "tags": list(value.tags),
                "specification_digest": value.specification_digest,
                "resource_generation": value.resource_generation,
                "identity_digest": value.identity_digest,
            }
        )

    @staticmethod
    def _decode(payload: bytes) -> tuple[str, ManagedPythonEnvironment]:
        try:
            data = json.loads(payload.decode("utf-8"))
            if not isinstance(data, dict) or data.get("schema") != _SCHEMA:
                raise ValueError("schema")
            status = data.get("status")
            if status not in {"registered", "rollback", "retired"}:
                raise ValueError("status")
            value = ManagedPythonEnvironment(
                environment_id=str(data["environment_id"]),
                scope=scope_from_data(data["scope"]),
                backend=str(data["backend"]),
                root=Path(str(data["root"])),
                python_path=Path(str(data["python_path"])),
                state=PythonEnvironmentState.REGISTERED,
                ownership=PythonEnvironmentOwnership(str(data["ownership"])),
                description=str(data.get("description", "")),
                tags=tuple(str(item) for item in data.get("tags", ())),
                specification_digest=str(data["specification_digest"]),
                resource_generation=int(data["resource_generation"]),
            )
            if data.get("identity_digest") != value.identity_digest:
                raise ValueError("identity digest")
            return str(status), value
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Python environment registry Event projection is invalid") from exc

    def _latest(self, environment_id: str) -> tuple[str, ManagedPythonEnvironment] | None:
        journal = self._journal(environment_id)
        try:
            payload = journal.read()
        except FileNotFoundError:
            return None
        return self._decode(payload)

    def put(self, value: ManagedPythonEnvironment) -> ManagedPythonEnvironment:
        self._validate_id(value.environment_id)
        current = self._latest(value.environment_id)
        if current is not None:
            status, previous = current
            if status == "registered":
                if previous.identity_digest != value.identity_digest:
                    raise RuntimeError(
                        "Python environment metadata identity drift within one resource generation: "
                        + value.environment_id
                    )
                return self._with_observed_state(value)
            if status == "retired" and value.resource_generation <= previous.resource_generation:
                raise RuntimeError(
                    "Python environment generation must advance after retirement: "
                    + value.environment_id
                )
            if status == "rollback" and value.resource_generation < previous.resource_generation:
                raise RuntimeError(
                    "Python environment generation regressed after rollback: "
                    + value.environment_id
                )
        self._journal(value.environment_id).append(
            self._payload(value, status="registered"),
            phase="registered",
            modality=TruthModality.OBSERVED,
            operation="python-environment-metadata",
        )
        return self._with_observed_state(value)

    def get(self, environment_id: str) -> ManagedPythonEnvironment:
        latest = self._latest(environment_id)
        if latest is None or latest[0] != "registered":
            raise KeyError(environment_id)
        return self._with_observed_state(latest[1])

    @staticmethod
    def _with_observed_state(value: ManagedPythonEnvironment) -> ManagedPythonEnvironment:
        state = (
            PythonEnvironmentState.READY
            if value.python_path.exists()
            else PythonEnvironmentState.MISSING
        )
        return ManagedPythonEnvironment(
            value.environment_id,
            value.scope,
            value.backend,
            value.root,
            value.python_path,
            state,
            value.ownership,
            value.description,
            value.tags,
            value.specification_digest,
            value.resource_generation,
        )

    def _environment_ids(self) -> tuple[str, ...]:
        ids = {path.stem for path in self._root.glob("*.json")}
        for event_root in self._root.glob("*.json.events"):
            ids.add(event_root.name[:-12])
        return tuple(sorted(ids))

    def all(self) -> tuple[ManagedPythonEnvironment, ...]:
        values = []
        for environment_id in self._environment_ids():
            try:
                values.append(self.get(environment_id))
            except KeyError:
                pass
        return tuple(values)

    def retire(self, expected: ManagedPythonEnvironment) -> bool:
        if type(expected) is not ManagedPythonEnvironment:
            raise TypeError("Python environment retirement requires ManagedPythonEnvironment")
        latest = self._latest(expected.environment_id)
        if latest is None:
            raise KeyError(expected.environment_id)
        status, current = latest
        if current.identity_digest != expected.identity_digest:
            raise RuntimeError(
                "stale Python environment retirement generation: "
                + expected.environment_id
            )
        if status == "retired":
            return True
        if status != "registered":
            raise RuntimeError(
                "Python environment cannot retire non-registered metadata: "
                + expected.environment_id
            )
        self._journal(expected.environment_id).append(
            self._payload(expected, status="retired"),
            phase="retired",
            modality=TruthModality.EVIDENCED,
            operation="python-environment-metadata",
        )
        return True

    def remove(self, environment_id: str) -> bool:
        """Publish non-terminal metadata rollback for failed create recovery."""

        try:
            current = self.get(environment_id)
        except KeyError:
            return False
        self._journal(environment_id).append(
            self._payload(current, status="rollback"),
            phase="rollback",
            modality=TruthModality.EVIDENCED,
            operation="python-environment-metadata",
        )
        return True

    def verify_projection_rebuild(self) -> None:
        for environment_id in self._environment_ids():
            self._journal(environment_id).verify_projection_rebuild()


__all__ = ["PythonEnvironmentRegistry"]
