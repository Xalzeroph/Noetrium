"""Causal Event transaction projection for Python environment lifecycle effects."""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from functools import lru_cache
from pathlib import Path

from noetrium_platform.infrastructure.lifecycle.python.api import (
    ManagedPythonEnvironment,
    PythonEnvironmentOwnership,
    PythonEnvironmentState,
)
from noetrium_platform.foundation.kernel.kernel import canonical_bytes
from noetrium_platform.foundation.kernel.truth import TruthModality
from noetrium_platform.foundation.api import (
    DirectoryLayoutPort,
    ManagedDirectoryKind,
    NoetriumUnit,
    scope_from_data,
    scope_to_data,
)
from noetrium_platform.foundation.kernel.event_store import (
    FileCausalEventStore,
)


_SCHEMA = "python.environment.lifecycle-transaction.v2"
_CREATE_PHASES = frozenset({"prepared", "materialized", "committed", "closed"})
_REMOVE_PHASES = frozenset({"prepared", "unregistered", "committed", "closed"})
_MODALITY = {
    "prepared": TruthModality.DECLARED,
    "materialized": TruthModality.OBSERVED,
    "unregistered": TruthModality.AUTHORIZED,
    "committed": TruthModality.EVIDENCED,
    "closed": TruthModality.EVIDENCED,
}


@dataclass(frozen=True, slots=True)
class PythonEnvironmentLifecycleTransaction:
    operation: str
    phase: str
    environment_id: str
    scope: NoetriumUnit
    backend: str
    root: Path
    python_path: Path
    ownership: PythonEnvironmentOwnership
    description: str
    tags: tuple[str, ...]
    specification_digest: str
    resource_generation: int

    def __post_init__(self) -> None:
        phases = (
            _CREATE_PHASES
            if self.operation == "create"
            else _REMOVE_PHASES if self.operation == "remove" else None
        )
        if phases is None or self.phase not in phases:
            raise ValueError("invalid Python environment lifecycle transaction phase")
        if not self.environment_id or any(
            char in self.environment_id for char in "/\\\x00\r\n"
        ):
            raise ValueError("invalid Python environment lifecycle transaction id")
        if not self.root.is_absolute() or not self.python_path.is_absolute():
            raise ValueError(
                "Python environment lifecycle transaction paths must be absolute"
            )
        if len(self.specification_digest) != 64:
            raise ValueError(
                "Python environment lifecycle transaction specification digest is invalid"
            )
        if type(self.resource_generation) is not int or self.resource_generation < 1:
            raise ValueError(
                "Python environment lifecycle transaction resource_generation must be positive"
            )

    def with_phase(self, phase: str) -> "PythonEnvironmentLifecycleTransaction":
        return replace(self, phase=phase)

    def environment(
        self,
        *,
        state: PythonEnvironmentState = PythonEnvironmentState.READY,
    ) -> ManagedPythonEnvironment:
        return ManagedPythonEnvironment(
            self.environment_id,
            self.scope,
            self.backend,
            self.root,
            self.python_path,
            state,
            self.ownership,
            self.description,
            self.tags,
            self.specification_digest,
            self.resource_generation,
        )


class PythonEnvironmentLifecycleTransactionStore:
    """Per-environment causal Event truth for crash recovery transitions."""

    def __init__(self, directories: DirectoryLayoutPort) -> None:
        self._root = (
            directories.root(ManagedDirectoryKind.STATE)
            / "python-environment-lifecycle"
        )
        self._root.mkdir(parents=True, exist_ok=True)
        self._journal_handles = lru_cache(maxsize=128)(self._new_journal)

    @staticmethod
    def _validate_id(environment_id: str) -> None:
        if not environment_id or any(
            char in environment_id for char in "/\\\x00\r\n"
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
    def _payload(value: PythonEnvironmentLifecycleTransaction) -> bytes:
        return canonical_bytes(
            {
                "schema": _SCHEMA,
                "operation": value.operation,
                "phase": value.phase,
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
            }
        )

    @staticmethod
    def _decode(payload: bytes) -> PythonEnvironmentLifecycleTransaction:
        try:
            document = json.loads(payload.decode("utf-8"))
            if not isinstance(document, dict) or document.get("schema") != _SCHEMA:
                raise ValueError("schema")
            return PythonEnvironmentLifecycleTransaction(
                operation=str(document["operation"]),
                phase=str(document["phase"]),
                environment_id=str(document["environment_id"]),
                scope=scope_from_data(document["scope"]),
                backend=str(document["backend"]),
                root=Path(str(document["root"])),
                python_path=Path(str(document["python_path"])),
                ownership=PythonEnvironmentOwnership(str(document["ownership"])),
                description=str(document["description"]),
                tags=tuple(str(item) for item in document["tags"]),
                specification_digest=str(document["specification_digest"]),
                resource_generation=int(document["resource_generation"]),
            )
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Python environment lifecycle Event projection is invalid"
            ) from exc

    def put(
        self, value: PythonEnvironmentLifecycleTransaction
    ) -> PythonEnvironmentLifecycleTransaction:
        current = self.latest(value.environment_id)
        if current is not None and current.phase != "closed":
            if (
                current.operation != value.operation
                or current.resource_generation != value.resource_generation
                or current.specification_digest != value.specification_digest
            ):
                raise RuntimeError(
                    "Python environment lifecycle transaction identity drifted"
                )
            if current == value:
                return current
            allowed = {
                "create": {
                    "prepared": {"materialized", "closed"},
                    "materialized": {"committed", "closed"},
                    "committed": {"closed"},
                },
                "remove": {
                    "prepared": {"unregistered"},
                    "unregistered": {"committed"},
                    "committed": {"closed"},
                },
            }
            if value.phase not in allowed[current.operation].get(current.phase, set()):
                raise RuntimeError(
                    "illegal Python environment lifecycle transition: "
                    f"{current.operation}:{current.phase}->{value.phase}"
                )
        elif current is not None and value.resource_generation < current.resource_generation:
            raise RuntimeError(
                "Python environment lifecycle generation regressed after close"
            )
        self._journal(value.environment_id).append(
            self._payload(value),
            phase=value.phase,
            modality=_MODALITY[value.phase],
            operation="python-environment-" + value.operation,
        )
        return value

    def latest(
        self, environment_id: str
    ) -> PythonEnvironmentLifecycleTransaction | None:
        journal = self._journal(environment_id)
        try:
            payload = journal.read()
        except FileNotFoundError:
            return None
        value = self._decode(payload)
        if value.environment_id != environment_id:
            raise RuntimeError(
                "Python environment lifecycle Event identity drifted: "
                + environment_id
            )
        return value

    def get(
        self, environment_id: str
    ) -> PythonEnvironmentLifecycleTransaction | None:
        value = self.latest(environment_id)
        return None if value is None or value.phase == "closed" else value

    def _environment_ids(self) -> tuple[str, ...]:
        ids = {path.stem for path in self._root.glob("*.json")}
        for event_root in self._root.glob("*.json.events"):
            ids.add(event_root.name[:-12])
        return tuple(sorted(ids))

    def all(self) -> tuple[PythonEnvironmentLifecycleTransaction, ...]:
        values = []
        for environment_id in self._environment_ids():
            value = self.get(environment_id)
            if value is not None:
                values.append(value)
        return tuple(values)

    def close(self, environment_id: str) -> None:
        current = self.get(environment_id)
        if current is None:
            return
        # `closed` is the terminal causal fact for either a committed operation
        # or a fully rolled-back failed operation. No transaction history is deleted.
        self.put(current.with_phase("closed"))

    def verify_projection_rebuild(self) -> None:
        for environment_id in self._environment_ids():
            self._journal(environment_id).verify_projection_rebuild()


__all__ = [
    "PythonEnvironmentLifecycleTransaction",
    "PythonEnvironmentLifecycleTransactionStore",
]
