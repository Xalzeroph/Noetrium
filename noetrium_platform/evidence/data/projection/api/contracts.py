from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar, Generic, runtime_checkable

T = TypeVar("T")
P = TypeVar("P")


@dataclass(frozen=True, slots=True)
class ProjectionCursor:
    source_id: str
    position: int
    source_digest: str

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.source_digest.strip():
            raise ValueError("projection cursor identity fields must be non-empty")
        if self.position < 0:
            raise ValueError("projection cursor position must be non-negative")


@dataclass(frozen=True, slots=True)
class ProjectionTail(Generic[T]):
    """A verified authoritative suffix extending one exact source watermark."""

    from_cursor: ProjectionCursor
    to_cursor: ProjectionCursor
    items: tuple[T, ...]

    def __post_init__(self) -> None:
        if self.from_cursor.source_id != self.to_cursor.source_id:
            raise ValueError("projection tail source identity mismatch")
        if self.to_cursor.position < self.from_cursor.position:
            raise ValueError("projection tail rewinds authoritative source")
        if self.to_cursor.position - self.from_cursor.position != len(self.items):
            raise ValueError("projection tail item count does not match cursor delta")


@dataclass(frozen=True, slots=True)
class ProjectionCheckpoint(Generic[P]):
    projector_id: str
    projector_version: str
    cursor: ProjectionCursor
    payload: P
    projection_digest: str


@runtime_checkable
class ProjectionReducerPort(Protocol, Generic[T, P]):
    projector_id: str
    projector_version: str

    def initial(self) -> P: ...
    def apply(self, state: P, item: T) -> P: ...
    def digest(self, state: P) -> str: ...


@runtime_checkable
class ProjectionCheckpointStorePort(Protocol, Generic[P]):
    def load(self, projector_id: str) -> ProjectionCheckpoint[P] | None: ...
    def save(self, checkpoint: ProjectionCheckpoint[P]) -> None: ...


__all__ = [
    "ProjectionCheckpoint",
    "ProjectionCheckpointStorePort",
    "ProjectionCursor",
    "ProjectionReducerPort",
    "ProjectionTail",
]
