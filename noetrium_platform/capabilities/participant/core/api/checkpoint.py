from __future__ import annotations

from dataclasses import dataclass
import hashlib

from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, canonical_digest

from .contracts import ParticipantRuntimeBinding


class ParticipantCheckpointIdentityMismatch(RuntimeError):
    """Checkpoint envelope does not belong to the exact bound runtime/session."""


@dataclass(frozen=True, slots=True)
class ParticipantCheckpointRef:
    """Portable checkpoint identity independent of Study or any concrete participant domain."""

    role: str
    runtime_binding_digest: str
    component_digest: str
    session_id: str
    payload_sha256: str

    def __post_init__(self) -> None:
        required = (
            self.role,
            self.runtime_binding_digest,
            self.component_digest,
            self.session_id,
            self.payload_sha256,
        )
        if any(not isinstance(value, str) or not value.strip() for value in required):
            raise ValueError("participant checkpoint identity fields must be non-empty")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ParticipantCheckpoint:
    """Generic participant checkpoint envelope.

    The participant implementation owns only opaque payload semantics.  The platform
    owns binding/session/integrity identity, so a runtime, configuration, role or
    session swap can never silently restore an incompatible payload.
    """

    ref: ParticipantCheckpointRef
    opaque_payload: bytes

    @classmethod
    def capture(
        cls,
        *,
        binding: ParticipantRuntimeBinding,
        component: ComponentIdentity,
        session_id: str,
        opaque_payload: bytes,
    ) -> "ParticipantCheckpoint":
        payload = bytes(opaque_payload)
        ref = ParticipantCheckpointRef(
            role=binding.role,
            runtime_binding_digest=binding.digest(),
            component_digest=canonical_digest(component),
            session_id=session_id,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
        )
        return cls(ref, payload)

    def verify(
        self,
        *,
        binding: ParticipantRuntimeBinding,
        component: ComponentIdentity,
        session_id: str,
    ) -> None:
        expected = (
            binding.role,
            binding.digest(),
            canonical_digest(component),
            session_id,
        )
        actual = (
            self.ref.role,
            self.ref.runtime_binding_digest,
            self.ref.component_digest,
            self.ref.session_id,
        )
        if actual != expected:
            raise ParticipantCheckpointIdentityMismatch(
                f"participant checkpoint binding/session mismatch: expected={expected!r} actual={actual!r}"
            )
        actual_payload_sha256 = hashlib.sha256(self.opaque_payload).hexdigest()
        if actual_payload_sha256 != self.ref.payload_sha256:
            raise ParticipantCheckpointIdentityMismatch(
                "participant checkpoint payload checksum mismatch: "
                f"role={self.ref.role!r} expected={self.ref.payload_sha256} actual={actual_payload_sha256}"
            )


__all__ = [
    "ParticipantCheckpoint",
    "ParticipantCheckpointIdentityMismatch",
    "ParticipantCheckpointRef",
]
