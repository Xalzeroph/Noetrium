from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_digest

from .contracts import EnvironmentIdentity


class EnvironmentBranchStateMismatch(RuntimeError):
    """A branch state cannot truthfully materialize the requested child state."""


def _require_sha256(value: str, field_name: str) -> str:
    if (
        type(value) is not str
        or value != value.lower()
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{field_name} must be a canonical sha256")
    return value


@dataclass(frozen=True, slots=True)
class EnvironmentBranchState:
    """Portable scientific state for search/experiment branching.

    Recovery checkpoints are session-bound durability artifacts. Branch state is
    deliberately different: it may be restored into a distinct child session,
    but only for the same environment implementation, task and generation.
    Providers own the opaque payload and the semantic state digest.
    """

    environment: EnvironmentIdentity
    source_session_id: str
    task_id: str
    generation: str
    state_schema_id: str
    state_digest: str
    payload_sha256: str
    opaque_payload: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.environment, EnvironmentIdentity):
            raise TypeError("environment branch state requires EnvironmentIdentity")
        for name, value in (
            ("source_session_id", self.source_session_id),
            ("task_id", self.task_id),
            ("generation", self.generation),
            ("state_schema_id", self.state_schema_id),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"environment branch state {name} is required")
        _require_sha256(self.state_digest, "environment branch state state_digest")
        _require_sha256(self.payload_sha256, "environment branch state payload_sha256")
        if type(self.opaque_payload) is not bytes or not self.opaque_payload:
            raise TypeError("environment branch state payload must be non-empty bytes")
        actual = sha256(self.opaque_payload).hexdigest()
        if actual != self.payload_sha256:
            raise EnvironmentBranchStateMismatch(
                "environment branch state payload checksum mismatch"
            )

    @classmethod
    def capture(
        cls,
        *,
        environment: EnvironmentIdentity,
        source_session_id: str,
        task_id: str,
        generation: str,
        state_schema_id: str,
        state_digest: str,
        opaque_payload: bytes,
    ) -> "EnvironmentBranchState":
        payload = bytes(opaque_payload)
        return cls(
            environment=environment,
            source_session_id=source_session_id,
            task_id=task_id,
            generation=generation,
            state_schema_id=state_schema_id,
            state_digest=state_digest,
            payload_sha256=sha256(payload).hexdigest(),
            opaque_payload=payload,
        )

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "environment": self.environment,
                "source_session_id": self.source_session_id,
                "task_id": self.task_id,
                "generation": self.generation,
                "state_schema_id": self.state_schema_id,
                "state_digest": self.state_digest,
                "payload_sha256": self.payload_sha256,
            }
        )

    def verify_for(
        self,
        *,
        environment: EnvironmentIdentity,
        task_id: str,
        generation: str,
    ) -> None:
        if self.environment != environment:
            raise EnvironmentBranchStateMismatch(
                "environment branch state implementation identity mismatch"
            )
        if self.task_id != task_id:
            raise EnvironmentBranchStateMismatch(
                "environment branch state task identity mismatch"
            )
        if self.generation != generation:
            raise EnvironmentBranchStateMismatch(
                "environment branch state generation mismatch"
            )
        actual = sha256(self.opaque_payload).hexdigest()
        if actual != self.payload_sha256:
            raise EnvironmentBranchStateMismatch(
                "environment branch state payload checksum mismatch"
            )


@runtime_checkable
class EnvironmentBranchStatePort(Protocol):
    """Provider-owned portable branch state, distinct from recovery checkpointing."""

    def capture_branch_state(self, context: ExecutionContext) -> EnvironmentBranchState: ...

    def restore_branch_state(
        self,
        state: EnvironmentBranchState,
        context: ExecutionContext,
    ) -> None: ...


__all__ = [
    "EnvironmentBranchState",
    "EnvironmentBranchStateMismatch",
    "EnvironmentBranchStatePort",
]
