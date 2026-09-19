from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.scope.api import ScopeIdentity


@dataclass(frozen=True, slots=True)
class DatasetIdentity:
    dataset_id: str
    version: str

    def __post_init__(self) -> None:
        if not self.dataset_id.strip() or not self.version.strip():
            raise ValueError("dataset identity/version must be non-empty")

    @property
    def key(self) -> str:
        return f"{self.dataset_id}@{self.version}"


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    """Portable scientific dataset identity; physical storage is deliberately external."""

    identity: DatasetIdentity
    scope: ScopeIdentity
    content_sha256: str
    schema_ref: str | None = None
    parent_versions: tuple[DatasetIdentity, ...] = ()
    tags: tuple[str, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        """Validate complete variable-cardinality dataset authority before acceptance.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: N is parent, tag, and metadata cardinality; duplicate or malformed lineage must fail closed.
        """
        if not isinstance(self.content_sha256, str) or len(self.content_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.content_sha256
        ):
            raise ValueError("dataset content_sha256 must be lowercase SHA-256")
        if self.schema_ref is not None and not self.schema_ref.strip():
            raise ValueError("dataset schema_ref must be non-empty when present")
        if any(not isinstance(parent, DatasetIdentity) for parent in self.parent_versions):
            raise ValueError("dataset parent_versions must contain DatasetIdentity values")
        parent_keys = [parent.key for parent in self.parent_versions]
        if len(set(parent_keys)) != len(parent_keys):
            raise ValueError("dataset parent_versions must be unique")
        if self.identity.key in parent_keys:
            raise ValueError("dataset parent_versions cannot contain the dataset itself")
        if any(not isinstance(value, str) or not value.strip() for value in self.tags):
            raise ValueError("dataset tags must be non-empty strings")
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("dataset tags must be unique")
        if any(not isinstance(pair, tuple) or len(pair) != 2 for pair in self.metadata):
            raise ValueError("dataset metadata must contain key/value pairs")
        keys = [key for key, _ in self.metadata]
        values = [value for _, value in self.metadata]
        if any(not isinstance(key, str) or not key.strip() for key in keys) or len(set(keys)) != len(keys):
            raise ValueError("dataset metadata keys must be non-empty and unique")
        if any(not isinstance(value, str) for value in values):
            raise ValueError("dataset metadata values must be strings")


@dataclass(frozen=True, slots=True)
class DatasetQuery:
    dataset_id: str | None = None
    scope: ScopeIdentity | None = None
    tag: str | None = None
    limit: int = 1000

    def __post_init__(self) -> None:
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or not 1 <= self.limit <= 10_000:
            raise ValueError("dataset query limit must be an integer in [1, 10000]")


__all__ = ["DatasetIdentity", "DatasetQuery", "DatasetVersion"]
