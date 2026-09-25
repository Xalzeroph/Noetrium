from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

_BACKEND_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


@dataclass(frozen=True, slots=True)
class PersistentSessionBackendConfig:
    """Backend-neutral configuration passed only to a backend factory.

    Options are canonical string pairs so the API does not import tmux/systemd
    implementation types. A concrete backend owns validation of its keys.
    """

    backend_id: str
    options: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not _BACKEND_RE.fullmatch(self.backend_id):
            raise ValueError("persistent-session backend_id must be a safe identifier")
        keys = [key for key, _ in self.options]
        if any(not key for key in keys) or len(keys) != len(set(keys)):
            raise ValueError("persistent-session backend options must have unique non-empty keys")
        if tuple(sorted(self.options)) != self.options:
            raise ValueError("persistent-session backend options must be sorted canonically")

    def as_dict(self) -> dict[str, str]:
        return dict(self.options)


@dataclass(frozen=True, slots=True)
class PersistentSessionStatusConfig:
    binding_root: Path
    session_name: str
    backend: PersistentSessionBackendConfig

    def __post_init__(self) -> None:
        if not self.session_name:
            raise ValueError("persistent-session status session_name required")


__all__ = ["PersistentSessionBackendConfig", "PersistentSessionStatusConfig"]
