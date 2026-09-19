from __future__ import annotations

from dataclasses import dataclass
import re

from noetrium_platform.foundation.scope.path.api import PathFlavor


_KEY = re.compile(r"[a-z][a-z0-9_.-]*")


@dataclass(frozen=True, slots=True)
class ResourceResolutionRequest:
    """Project-neutral request for one frozen resource binding."""

    binding_id: str
    base_path: str
    paths: tuple[tuple[str, str], ...] = ()
    executables: tuple[tuple[str, str], ...] = ()
    flavor: PathFlavor = PathFlavor.NATIVE

    def __post_init__(self) -> None:
        if not self.binding_id.strip():
            raise ValueError("resource binding_id must be non-empty")
        if not self.base_path.strip():
            raise ValueError("resource base_path must be non-empty")
        self._validate_keys(self.paths, "path")
        self._validate_keys(self.executables, "executable")

    @staticmethod
    def _validate_keys(rows: tuple[tuple[str, str], ...], kind: str) -> None:
        names = [name for name, _ in rows]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate resource {kind} key")
        if any(_KEY.fullmatch(name) is None for name in names):
            raise ValueError(f"resource {kind} keys must be safe tokens")


@dataclass(frozen=True, slots=True)
class ResolvedResourceBinding:
    """Immutable named resource map consumed by project composition."""

    binding_id: str
    flavor: PathFlavor
    paths: tuple[tuple[str, str], ...]
    executables: tuple[tuple[str, str], ...]
    resolution_digest: str

    def __post_init__(self) -> None:
        if not self.binding_id.strip() or not self.resolution_digest.strip():
            raise ValueError("resolved resource identity is incomplete")
        if len({key for key, _ in self.paths}) != len(self.paths):
            raise ValueError("resolved resource paths contain duplicate keys")
        if len({key for key, _ in self.executables}) != len(self.executables):
            raise ValueError("resolved resource executables contain duplicate keys")

    def path(self, key: str) -> str:
        try:
            return dict(self.paths)[key]
        except KeyError as exc:
            raise KeyError(f"resource path is not bound: {key}") from exc

    def executable(self, key: str) -> str:
        try:
            return dict(self.executables)[key]
        except KeyError as exc:
            raise KeyError(f"resource executable is not bound: {key}") from exc


__all__ = ["ResourceResolutionRequest", "ResolvedResourceBinding"]
