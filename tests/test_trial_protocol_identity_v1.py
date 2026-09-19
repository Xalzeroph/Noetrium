from __future__ import annotations

from dataclasses import replace

import pytest

from tests_support import model_role_for_test

from noetrium_platform.foundation.kernel.kernel import (
    MachineStatus,
    canonical_digest,
)
from noetrium_platform.research.execution.machines import (
    ProgramNodeResult,
    RuntimeConcern,
    RuntimeProgramBuilder,
)
from noetrium_platform.research.execution.workflow.runtime.program_trial import (
    RuntimeProgramTrialProtocol,
    TrialProgramOperation,
)
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentSpec,
    ExperimentTrialProtocolIdentityMismatch,
)
from noetrium_platform.research.experimentation.experiment.runtime import (
    trial_protocol_identity,
    verify_trial_protocol_identity,
)


def _protocol() -> RuntimeProgramTrialProtocol:
    program = (
        RuntimeProgramBuilder.create(
            program_id="trial.identity-test",
            version="1",
            state_schema="trial.identity-test.state.v1",
            entrypoint="finish",
        )
        .semantic(
            "finish",
            RuntimeConcern.EVENT,
            "trial.identity-test.finish",
        )
        .build()
    )

    def finish(request, surface, frame):
        del request, surface
        frame.primary_result = object()
        return ProgramNodeResult(status=MachineStatus.COMPLETED)

    return RuntimeProgramTrialProtocol(
        protocol_id="offline-score.v1",
        surface_id="offline.score.surface.v1",
        program=program,
        operations=(
            TrialProgramOperation(
                "trial.identity-test.finish",
                finish,
                canonical_digest({
                    "operation": "trial.identity-test.finish",
                    "implementation_revision": 1,
                }),
            ),
        ),
    )


def _spec(protocol: RuntimeProgramTrialProtocol) -> ExperimentSpec:
    return ExperimentSpec(
        "experiment-1",
        "study-1",
        "project-1",
        (),
        (model_role_for_test(),),
        "2" * 64,
        "3" * 64,
        1,
        protocol.protocol_id,
        protocol.configuration_digest,
    )


def test_trial_protocol_identity_is_program_backed_and_exact() -> None:
    protocol = _protocol()
    identity = trial_protocol_identity(protocol)
    assert identity.protocol_id == "offline-score.v1"
    assert identity.configuration_digest == protocol.configuration_digest
    verify_trial_protocol_identity(_spec(protocol), identity)


def test_trial_protocol_identity_drift_fails_closed() -> None:
    protocol = _protocol()
    identity = trial_protocol_identity(protocol)
    with pytest.raises(
        ExperimentTrialProtocolIdentityMismatch,
        match="identity mismatch",
    ):
        verify_trial_protocol_identity(
            replace(_spec(protocol), trial_protocol_id="custom-state-machine.v2"),
            identity,
        )


def test_arbitrary_python_trial_runner_is_rejected() -> None:
    class LegacyRunner:
        protocol_id = "legacy"
        configuration_digest = "1" * 64
        surface_id = "legacy"

        def run(self, *args, **kwargs):
            del args, kwargs
            return object()

    with pytest.raises(TypeError, match="RuntimeProgramTrialProtocol"):
        trial_protocol_identity(LegacyRunner())  # type: ignore[arg-type]
