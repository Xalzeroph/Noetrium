from __future__ import annotations

from tests_support import FakeParticipantResolver, runtime_identity_for_test, model_role_for_test, build_experiment_runtime_for_test

from noetrium_platform.composition.participants.generic import generic_participant_adapter
from noetrium_platform.capabilities.participant.core.api import ParticipantImplementationIdentity
from tests_support import ExperimentRuntimeForTest as ExperimentRuntime
from noetrium_platform.research.execution.workflow.api import ExecutionTrialProtocolKind, TrialCycleExecution
from noetrium_platform.research.experimentation.lifecycle.api import ExperimentParticipantSpec, ExperimentSpec


class ExternalRobotSession:
    restored: list[bytes] = []

    def __init__(self, identity: ParticipantImplementationIdentity, session_id: str) -> None:
        self.implementation = identity
        self.session_id = session_id
        self.state = b"robot-state-v1"

    def checkpoint(self):
        return self.state

    def restore(self, payload):
        self.state = payload
        type(self).restored.append(self.state)

    def close(self): pass


class ExternalRobot:
    implementation_identity = ParticipantImplementationIdentity("robot", "arm-vendor-sdk", "7", "1", "3")

    def open_session(self, *, session_id: str, services: object):
        del services
        return ExternalRobotSession(self.implementation_identity, session_id)


class NoOpTrialProtocol:
    protocol_kind = ExecutionTrialProtocolKind.RUNTIME_PROGRAM
    protocol_id = "external-robot-noop.v1"
    surface_id = "empty.operations.v1"
    configuration_digest = "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"

    def run(self, operations, context, *, task, input_kind, input_payload):
        del operations, input_kind
        return TrialCycleExecution(str(task), input_payload, context, ())


def _spec():
    return ExperimentSpec(
        experiment_id="external-robot-study",
        study_id="default-study",
        project_id="default-project",
        participants=(ExperimentParticipantSpec("physical_arm", ParticipantImplementationIdentity("robot", "arm-vendor-sdk", "7", "1", "3"), runtime_identity_for_test("robot"), "d" * 64),),
        model_roles=(model_role_for_test(),), workload_digest="b" * 64, seed_digest="c" * 64,
        repetitions=1, trial_protocol_id="external-robot-noop.v1",
        trial_protocol_configuration_digest="44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    )


def _runtime():
    participants = FakeParticipantResolver()
    participants.register("robot", "arm-vendor-sdk", ExternalRobot)
    from tests_support import EmptyWorkflowSurfaceFactory
    return build_experiment_runtime_for_test(
        participant_adapters=tuple(generic_participant_adapter(kind, participants) for kind in participants.kinds()),
        trial_protocol=NoOpTrialProtocol(),
        workflow_surface_factories=(EmptyWorkflowSurfaceFactory(),),
    )


def test_third_party_participant_needs_no_study_adapter():
    result = _runtime().execute_cycle(_spec(), task="robot", input_payload={"x": 1})
    assert result.primary_result == {"x": 1}
    ids = [row.operation_id for row in result.operation_results]
    assert any("robot.resolve:physical_arm" in row for row in ids)
    assert any("robot.open_session:physical_arm" in row for row in ids)
    assert any("robot.close:physical_arm" in row for row in ids)
