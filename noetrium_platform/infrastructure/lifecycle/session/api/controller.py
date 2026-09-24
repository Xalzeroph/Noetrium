from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Protocol

from noetrium_platform.foundation.api import is_absolute_target_path
from noetrium_platform.foundation.kernel.kernel.durability import sha256_file

from .contracts import PersistentSessionSpec, process_environment_digest


from noetrium_platform.foundation.kernel.kernel.durability import sha256_bytes
class PersistentSessionLaunchManifestPort(Protocol):
    """Minimal read-only identity needed to bind an outer controller session."""

    def digest(self) -> str: ...


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
            digest, _launcher_size = sha256_file(launcher)
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
        return sha256_bytes(raw)

    def environment_digest(self) -> str:
        return process_environment_digest(self.environment)


__all__ = ["PersistentSessionLaunchManifestPort", "RuntimeControllerCommand"]
