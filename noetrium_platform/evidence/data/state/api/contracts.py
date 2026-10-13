from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import JsonValue


@dataclass(frozen=True, slots=True)
class AggregateValue:
    aggregate_id: str
    version: int
    generation: str
    digest: str
    payload: JsonValue

    def __post_init__(self) -> None:
        if not self.aggregate_id.strip() or not self.generation.strip() or not self.digest.strip():
            raise ValueError("aggregate identity, generation and digest must be non-empty")
        if isinstance(self.version, bool) or self.version < 0:
            raise ValueError("aggregate version must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class AtomicMutation:
    aggregate_id: str
    expected_version: int
    expected_generation: str
    new_generation: str
    new_digest: str
    new_payload: JsonValue

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.aggregate_id,
                self.expected_generation,
                self.new_generation,
                self.new_digest,
            )
        ):
            raise ValueError("atomic mutation identity/generation/digest fields must be non-empty")
        if isinstance(self.expected_version, bool) or self.expected_version < 0:
            raise ValueError("atomic mutation expected_version must be a non-negative integer")


__all__ = ["AggregateValue", "AtomicMutation"]
