from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.api import (
    ExecutionTrialProtocolPort,
    require_execution_trial_protocol,
)

from .contracts import ExperimentSpec


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


def trial_protocol_identity(
    trial_protocol: ExecutionTrialProtocolPort,
) -> ExperimentTrialProtocolIdentity:
    """Freeze the exact scientific identity of one execution trial protocol."""

    trial_protocol = require_execution_trial_protocol(trial_protocol)
    protocol_id = trial_protocol.protocol_id
    if not isinstance(protocol_id, str) or not protocol_id.strip():
        raise ValueError(
            "ExecutionTrialProtocolPort must expose a stable non-empty protocol_id"
        )
    configuration_digest = getattr(trial_protocol, "configuration_digest", None)
    if (
        type(configuration_digest) is not str
        or len(configuration_digest) != 64
        or any(ch not in "0123456789abcdef" for ch in configuration_digest)
    ):
        raise ValueError(
            "ExecutionTrialProtocolPort.configuration_digest must be lowercase SHA-256"
        )
    return ExperimentTrialProtocolIdentity(protocol_id, configuration_digest)


def verify_trial_protocol_identity(
    spec: ExperimentSpec,
    identity: ExperimentTrialProtocolIdentity,
) -> None:
    """Fail closed when a frozen Study and bound trial protocol drift."""

    expected = (
        spec.trial_protocol_id,
        spec.trial_protocol_configuration_digest,
    )
    actual = (
        identity.protocol_id,
        identity.configuration_digest,
    )
    if expected != actual:
        raise ExperimentTrialProtocolIdentityMismatch(
            "frozen Experiment trial protocol identity mismatch: "
            f"expected id={expected[0]!r} config={expected[1]!r}, "
            f"actual id={actual[0]!r} config={actual[1]!r}"
        )


__all__ = [
    "ExperimentTrialProtocolIdentity",
    "ExperimentTrialProtocolIdentityMismatch",
    "trial_protocol_identity",
    "verify_trial_protocol_identity",
]
