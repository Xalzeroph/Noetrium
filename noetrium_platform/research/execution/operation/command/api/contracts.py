from __future__ import annotations

from dataclasses import dataclass
import math
import re
import time

_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _required(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text")
    resolved = value.strip()
    if not resolved:
        raise ValueError(f"{name} required")
    return resolved


@dataclass(frozen=True, slots=True)
class CommandId:
    value: str
    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _required(self.value, "command_id"))


@dataclass(frozen=True, slots=True)
class CommandDeduplicationKey:
    value: str
    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _required(self.value, "command deduplication key"))


@dataclass(frozen=True, slots=True)
class ExecutionCommand:
    """Immutable execution intent. It is deliberately not an Operation identity."""
    command_id: CommandId
    command_type: str
    payload_schema: str
    payload_digest: str
    submitted_at_unix: float
    deduplication_key: CommandDeduplicationKey | None = None
    deadline_unix: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.command_id, CommandId):
            raise TypeError("command_id must be CommandId")
        if self.deduplication_key is not None and not isinstance(self.deduplication_key, CommandDeduplicationKey):
            raise TypeError("deduplication_key must be CommandDeduplicationKey or null")
        object.__setattr__(self, "command_type", _required(self.command_type, "command_type"))
        object.__setattr__(self, "payload_schema", _required(self.payload_schema, "payload_schema"))
        if not isinstance(self.payload_digest, str):
            raise TypeError("payload_digest must be text")
        digest = self.payload_digest.strip().lower()
        if not _SHA256.fullmatch(digest):
            raise ValueError("payload_digest must be a SHA-256 hex digest")
        object.__setattr__(self, "payload_digest", digest)
        if isinstance(self.submitted_at_unix, bool) or not isinstance(self.submitted_at_unix, (int, float)):
            raise TypeError("submitted_at_unix must be numeric")
        submitted_at = float(self.submitted_at_unix)
        if not math.isfinite(submitted_at) or submitted_at < 0:
            raise ValueError("submitted_at_unix must be a finite non-negative timestamp")
        object.__setattr__(self, "submitted_at_unix", submitted_at)
        if self.deadline_unix is not None:
            if isinstance(self.deadline_unix, bool) or not isinstance(self.deadline_unix, (int, float)):
                raise TypeError("deadline_unix must be numeric or null")
            deadline = float(self.deadline_unix)
            if not math.isfinite(deadline) or deadline <= submitted_at:
                raise ValueError("command deadline must be finite and after submission")
            object.__setattr__(self, "deadline_unix", deadline)

    @classmethod
    def create(cls, *, command_id: str, command_type: str, payload_schema: str,
               payload_digest: str, deduplication_key: str | None = None,
               deadline_unix: float | None = None, now_unix: float | None = None) -> "ExecutionCommand":
        return cls(CommandId(command_id), command_type, payload_schema, payload_digest,
                   time.time() if now_unix is None else now_unix,
                   None if deduplication_key is None else CommandDeduplicationKey(deduplication_key),
                   deadline_unix)


__all__ = ["CommandDeduplicationKey", "CommandId", "ExecutionCommand"]
