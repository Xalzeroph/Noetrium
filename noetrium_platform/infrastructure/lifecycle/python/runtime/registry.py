from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.foundation.api import (
    DirectoryLayoutPort,
    ManagedDirectoryKind,
    scope_from_data,
    scope_to_data,
)
from noetrium_platform.infrastructure.lifecycle.python.api import (
    ManagedPythonEnvironment,
    PythonEnvironmentOwnership,
    PythonEnvironmentRetired,
    PythonEnvironmentState,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    atomic_replace_bytes,
    durable_unlink,
    fsync_directory,
)


class PythonEnvironmentRegistry:
    """Authoritative metadata with terminal explicit-retirement identities."""

    def __init__(self, directories: DirectoryLayoutPort) -> None:
        self._root = (
            directories.root(ManagedDirectoryKind.STATE)
            / "python-environments"
        )
        created = not self._root.exists()
        self._root.mkdir(parents=True, exist_ok=True)
        if created:
            fsync_directory(self._root.parent)
        self._retired_root = self._root / "_retired"
        self._retired_root.mkdir(parents=True, exist_ok=True)

    def _path(self, environment_id: str) -> Path:
        return self._root / f"{environment_id}.json"

    def _retired_path(self, environment_id: str) -> Path:
        return self._retired_root / f"{environment_id}.sha256"

    def ensure_not_retired(self, environment_id: str) -> None:
        self._validate_id(environment_id)
        if self._retired_path(environment_id).exists():
            raise PythonEnvironmentRetired(environment_id)

    def is_retired(self, environment_id: str) -> bool:
        self._validate_id(environment_id)
        return self._retired_path(environment_id).exists()

    def put(
        self,
        value: ManagedPythonEnvironment,
    ) -> ManagedPythonEnvironment:
        self._validate_id(value.environment_id)
        self.ensure_not_retired(value.environment_id)
        payload = json.dumps(
            {
                "environment_id": value.environment_id,
                "scope": scope_to_data(value.scope),
                "backend": value.backend,
                "root": str(value.root),
                "python_path": str(value.python_path),
                "ownership": value.ownership.value,
                "description": value.description,
                "tags": list(value.tags),
                "specification_digest": value.specification_digest,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        atomic_replace_bytes(self._path(value.environment_id), payload)
        return value

    def get(
        self,
        environment_id: str,
    ) -> ManagedPythonEnvironment:
        self._validate_id(environment_id)
        if self.is_retired(environment_id):
            raise PythonEnvironmentRetired(environment_id)
        return self._read(environment_id)

    def _read(
        self,
        environment_id: str,
    ) -> ManagedPythonEnvironment:
        path = self._path(environment_id)
        if not path.exists():
            raise KeyError(environment_id)
        data = json.loads(path.read_text("utf-8"))
        specification_digest = str(
            data.get("specification_digest", "")
        )
        if len(specification_digest) != 64:
            raise RuntimeError(
                "Python environment registry entry lacks an immutable "
                f"specification digest: {environment_id}"
            )
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
            specification_digest=specification_digest,
        )
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
        )

    def all(self) -> tuple[ManagedPythonEnvironment, ...]:
        return tuple(
            self._read(path.stem)
            for path in sorted(self._root.glob("*.json"))
            if not self._retired_path(path.stem).exists()
        )

    def retire(
        self,
        expected: ManagedPythonEnvironment,
    ) -> bool:
        """Publish terminal identity before deleting active metadata.

        The expected value comes from the lifecycle transaction for managed
        removal or from the current registry row for external unregister.
        """

        if type(expected) is not ManagedPythonEnvironment:
            raise TypeError(
                "Python environment retirement requires "
                "ManagedPythonEnvironment"
            )
        self._validate_id(expected.environment_id)
        path = self._path(expected.environment_id)
        retired = self._retired_path(expected.environment_id)
        digest = expected.identity_digest

        if retired.exists():
            if retired.read_text("ascii").strip() != digest:
                raise RuntimeError(
                    "Python environment retirement generation drifted: "
                    f"{expected.environment_id}"
                )
        else:
            if path.exists():
                current = self._read(expected.environment_id)
                if current.identity_digest != digest:
                    raise RuntimeError(
                        "stale Python environment retirement generation: "
                        f"{expected.environment_id}"
                    )
            atomic_replace_bytes(
                retired,
                (digest + "\n").encode("ascii"),
            )

        if path.exists():
            current = self._read(expected.environment_id)
            if current.identity_digest != digest:
                raise RuntimeError(
                    "retired Python environment metadata drifted: "
                    f"{expected.environment_id}"
                )
            durable_unlink(path)
        return True

    def remove(self, environment_id: str) -> bool:
        """Non-terminal metadata rollback used only by failed create recovery."""

        self._validate_id(environment_id)
        path = self._path(environment_id)
        if not path.exists():
            return False
        if self.is_retired(environment_id):
            raise RuntimeError(
                "cannot rollback metadata for a retired Python environment: "
                f"{environment_id}"
            )
        durable_unlink(path)
        return True

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


__all__ = ["PythonEnvironmentRegistry"]
