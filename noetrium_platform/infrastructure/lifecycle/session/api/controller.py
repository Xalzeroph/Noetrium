from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Protocol

from noetrium_platform.foundation.scope.path.api import is_absolute_target_path

from .contracts import PersistentSessionSpec, process_environment_digest


class PersistentSessionLaunchManifestPort(Protocol):
    """Minimal read-only identity needed to bind an outer controller session."""

    def digest(self) -> str: ...


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class RuntimeControllerCommand:
    """Frozen command identity for the persistent outer runtime controller."""

    argv: tuple[str, ...]
    cwd: str
    environment: tuple[tuple[str, str], ...] = ()
    launcher_binary_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.argv:
            raise ValueError("runtime controller argv required")
        if not is_absolute_target_path(self.cwd):
            raise ValueError("runtime controller cwd must be absolute")
        launcher = Path(self.argv[0])
        if not is_absolute_target_path(self.argv[0]):
            raise ValueError("runtime controller launcher must be an absolute path")
        process_environment_digest(self.environment)
        digest = self.launcher_binary_sha256
        if not digest:
            if not launcher.is_file():
                raise FileNotFoundError(f"runtime controller launcher missing: {launcher}")
            digest = _sha256_file(launcher)
            object.__setattr__(self, "launcher_binary_sha256", digest)
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower()):
            raise ValueError("runtime controller launcher identity must be SHA-256")

    def digest(self) -> str:
        raw = json.dumps(
            {
                "argv": self.argv,
                "cwd": self.cwd,
                "launcher_binary_sha256": self.launcher_binary_sha256,
                "environment": self.environment,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def environment_digest(self) -> str:
        return process_environment_digest(self.environment)


__all__ = ["PersistentSessionLaunchManifestPort", "RuntimeControllerCommand"]
