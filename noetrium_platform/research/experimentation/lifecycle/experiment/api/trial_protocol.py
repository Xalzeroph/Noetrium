from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest


@dataclass(frozen=True, slots=True)
class ExperimentTrialProtocolIdentity:
    """Frozen scientific identity of one RuntimeProgram-backed trial protocol."""

    protocol_id: str
    configuration_digest: str

    def __post_init__(self) -> None:
        if not self.protocol_id.strip():
            raise ValueError("protocol_id must be non-empty")
        if (
            type(self.configuration_digest) is not str
            or len(self.configuration_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.configuration_digest)
        ):
            raise ValueError(
                "configuration_digest must be lowercase SHA-256"
            )

    def digest(self) -> str:
        return canonical_digest({
            "protocol_id": self.protocol_id,
            "configuration_digest": self.configuration_digest,
        })


class ExperimentTrialProtocolIdentityMismatch(RuntimeError):
    pass


__all__ = [
    "ExperimentTrialProtocolIdentity",
    "ExperimentTrialProtocolIdentityMismatch",
]
