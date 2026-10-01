from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest, freeze_json, thaw_json


class SoftwareActionTimeoutError(RuntimeError):
    """Software action exceeded its declared execution budget."""


class SoftwareActionKind(StrEnum):
    LIST = "list"
    READ = "read"
    EDIT = "edit"
    EXECUTE = "execute"
    TEST = "test"
    BUILD = "build"


@dataclass(frozen=True, slots=True)
class SoftwareContextPolicy:
    """Model-facing context bounds for repository environments."""

    max_text_chars: int = 12_000
    max_workspace_files: int = 512
    max_list_files: int = 512

    def __post_init__(self) -> None:
        if (
            type(self.max_text_chars) is not int
            or self.max_text_chars < 1_000
            or type(self.max_workspace_files) is not int
            or self.max_workspace_files < 1
            or type(self.max_list_files) is not int
            or self.max_list_files < 1
        ):
            raise ValueError("software context policy bounds are invalid")

    def record(self) -> dict[str, int]:
        return {
            "max_text_chars": self.max_text_chars,
            "max_workspace_files": self.max_workspace_files,
            "max_list_files": self.max_list_files,
        }


@dataclass(frozen=True, slots=True)
class SoftwareEnvironmentSpec:
    environment_id: str
    revision: str
    workspace_root: str
    repository_digest: str = ""
    supported_actions: tuple[SoftwareActionKind, ...] = ()
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    context_policy: SoftwareContextPolicy = field(default_factory=SoftwareContextPolicy)

    def __post_init__(self) -> None:
        if not self.environment_id.strip() or not self.revision.strip() or not self.workspace_root.strip():
            raise ValueError("software environment identity is required")
        if any(not isinstance(item, SoftwareActionKind) for item in self.supported_actions):
            raise TypeError("software actions must use SoftwareActionKind")
        if len(self.supported_actions) != len(set(self.supported_actions)):
            raise ValueError("software actions must be unique")
        object.__setattr__(self, "metadata", freeze_json(self.metadata or {}))

    @property
    def spec_digest(self) -> str:
        return canonical_digest({
            "environment_id": self.environment_id, "revision": self.revision,
            "workspace_root": self.workspace_root, "repository_digest": self.repository_digest,
            "supported_actions": [item.value for item in self.supported_actions],
            "metadata": thaw_json(self.metadata),
            "context_policy": self.context_policy.record(),
        })


__all__ = [
    "SoftwareActionKind",
    "SoftwareActionTimeoutError",
    "SoftwareContextPolicy",
    "SoftwareEnvironmentSpec",
]
