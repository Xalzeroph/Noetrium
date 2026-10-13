from __future__ import annotations

import pytest

from noetrium_platform.research.execution.workflow.api import (
    ExecutionTrialProtocolKind,
    TrialCycleExecution,
)
from noetrium_platform.research.experimentation.lifecycle.experiment.api.trial_protocol import (
    ExperimentTrialProtocolIdentityMismatch,
    trial_protocol_identity,
    verify_trial_protocol_identity,
)
from noetrium_platform.research.experimentation.lifecycle.experiment.api.unit_semantics import (
    experiment_unit,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    trial_protocol_configuration_digest,
    trial_protocol_id,
)


class _Protocol:
    protocol_kind = ExecutionTrialProtocolKind.RUNTIME_PROGRAM
    protocol_id = "offline-score.v1"
    surface_id = "offline.score.surface.v1"
    configuration_digest = "4" * 64

    def run(
        self,
        surface,
        context,
        *,
        task,
        input_kind,
        input_payload,
        control,
    ) -> TrialCycleExecution:
        del surface, task, input_kind, control
        return TrialCycleExecution(
            str(context.run_id),
            input_payload,
            context,
            (),
        )


def _spec(protocol_id_value: str = "offline-score.v1"):
    return experiment_unit(
        "experiment-1",
        study_id="study-1",
        project_id="project-1",
        participants=(),
        model_roles=(),
        workload_digest="2" * 64,
        seed_digest="3" * 64,
        repetitions=1,
        trial_protocol_id=protocol_id_value,
        trial_protocol_configuration_digest="4" * 64,
    )


def test_trial_protocol_identity_is_unit_backed_and_exact() -> None:
    protocol = _Protocol()
    identity = trial_protocol_identity(protocol)
    assert trial_protocol_id(identity) == "offline-score.v1"
    assert trial_protocol_configuration_digest(identity) == protocol.configuration_digest
    verify_trial_protocol_identity(_spec(), identity)


def test_trial_protocol_identity_drift_fails_closed() -> None:
    identity = trial_protocol_identity(_Protocol())
    with pytest.raises(
        ExperimentTrialProtocolIdentityMismatch,
        match="identity mismatch",
    ):
        verify_trial_protocol_identity(_spec("custom-state-machine.v2"), identity)


def test_arbitrary_python_trial_runner_is_rejected() -> None:
    class LegacyRunner:
        protocol_id = "legacy"
        configuration_digest = "1" * 64
        surface_id = "legacy"

        def run(self, *args, **kwargs):
            del args, kwargs
            return object()

    with pytest.raises(TypeError, match="ExecutionTrialProtocolPort"):
        trial_protocol_identity(LegacyRunner())  # type: ignore[arg-type]
