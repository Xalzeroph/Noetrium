from __future__ import annotations

from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentSpec,
    ExperimentTrialProtocolIdentity,
    ExperimentTrialProtocolIdentityMismatch,
)
from noetrium_platform.research.execution.workflow.runtime.program_trial import (
    RuntimeProgramTrialProtocol,
)


def trial_protocol_identity(trial_protocol: RuntimeProgramTrialProtocol) -> ExperimentTrialProtocolIdentity:
    if not isinstance(trial_protocol, RuntimeProgramTrialProtocol):
        raise TypeError(
            "trial protocol identity requires RuntimeProgramTrialProtocol"
        )
    protocol_id = trial_protocol.protocol_id
    if not isinstance(protocol_id, str) or not protocol_id.strip():
        raise ValueError("RuntimeProgramTrialProtocol must expose a stable non-empty protocol_id")
    configuration_digest = getattr(trial_protocol, "configuration_digest", None)
    if type(configuration_digest) is not str or len(configuration_digest) != 64 or any(ch not in "0123456789abcdef" for ch in configuration_digest):
        raise ValueError("RuntimeProgramTrialProtocol.configuration_digest must be lowercase SHA-256")
    return ExperimentTrialProtocolIdentity(protocol_id, configuration_digest)


def verify_trial_protocol_identity(spec: ExperimentSpec, identity: ExperimentTrialProtocolIdentity) -> None:
    expected = (spec.trial_protocol_id, spec.trial_protocol_configuration_digest)
    actual = (identity.protocol_id, identity.configuration_digest)
    if expected != actual:
        raise ExperimentTrialProtocolIdentityMismatch(
            "frozen Experiment trial protocol identity mismatch: "
            f"expected id={expected[0]!r} config={expected[1]!r}, "
            f"actual id={actual[0]!r} config={actual[1]!r}"
        )


__all__ = ["verify_trial_protocol_identity", "trial_protocol_identity"]
