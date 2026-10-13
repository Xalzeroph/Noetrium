from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.research.execution.api import (
    ExecutionTrialProtocolPort,
    require_execution_trial_protocol,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    trial_protocol_configuration_digest,
    trial_protocol_id,
    trial_protocol_unit,
)
from .unit_semantics import experiment_value, require_experiment_unit


class ExperimentTrialProtocolIdentityMismatch(RuntimeError):
    pass


def trial_protocol_identity(
    trial_protocol: ExecutionTrialProtocolPort,
) -> NoetriumUnit:
    """Freeze one execution trial protocol directly as immutable Unit semantics."""

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
    return trial_protocol_unit(protocol_id, configuration_digest)


def verify_trial_protocol_identity(
    spec: NoetriumUnit,
    identity: NoetriumUnit,
) -> None:
    """Fail closed when frozen Experiment Unit and trial-protocol Unit drift."""

    spec = require_experiment_unit(spec)
    expected = (
        str(experiment_value(spec, "trial_protocol_id")),
        str(experiment_value(spec, "trial_protocol_configuration_digest")),
    )
    actual = (
        trial_protocol_id(identity),
        trial_protocol_configuration_digest(identity),
    )
    if expected != actual:
        raise ExperimentTrialProtocolIdentityMismatch(
            "frozen Experiment trial protocol identity mismatch: "
            f"expected id={expected[0]!r} config={expected[1]!r}, "
            f"actual id={actual[0]!r} config={actual[1]!r}"
        )


__all__ = [
    "ExperimentTrialProtocolIdentityMismatch",
    "trial_protocol_identity",
    "verify_trial_protocol_identity",
]
