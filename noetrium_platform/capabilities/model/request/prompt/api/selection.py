from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def _sha256(value: object, field: str) -> str:
    digest = _text(value, field)
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return digest


@dataclass(frozen=True, slots=True)
class PromptSelectionIdentity:
    generation_id: str
    prompt_id: str
    prompt_digest: str
    role: str

    def __post_init__(self) -> None:
        _text(self.generation_id, "prompt selection generation id")
        _text(self.prompt_id, "prompt selection prompt id")
        _sha256(self.prompt_digest, "prompt selection digest")
        _text(self.role, "prompt selection role")
    def digest(self) -> str:
        return canonical_digest(self)


@runtime_checkable
class PromptSelectionPort(Protocol):
    """Read-only projection of exact prompt identity for author compilation."""

    def resolve_selection(self, prompt_id: str) -> PromptSelectionIdentity: ...


__all__ = ["PromptSelectionIdentity", "PromptSelectionPort"]
