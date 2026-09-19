from __future__ import annotations

from tests_support import model_role_for_test

from noetrium_platform.composition.experiment_runtime import build_experiment_runtime
from dataclasses import dataclass
from typing import get_type_hints

import pytest

from noetrium_platform.composition.participants.generic import generic_participant_adapter
from noetrium_platform.capabilities.participant.core.api.contracts import (
    ParticipantImplementationIdentity,
    ParticipantRuntimeBinding,
    )
from noetrium_platform.capabilities.participant.binding.api.contracts import ParticipantBindingResolverPort
from noetrium_platform.capabilities.participant.core.api.bound import BoundParticipant
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantRuntimeEndpoint, ParticipantRuntimeHandle
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.execution.workflow.api import TrialCycleExecution
from noetrium_platform.research.experimentation.experiment.api import ExperimentParticipantSpec, ExperimentSpec
from tests_support import EmptyWorkflowSurfaceFactory, frozen_runtime_manifest, run_launch_manifest, runtime_identity_for_test


class RemoteSessionProxy:
    def __init__(self, implementation: ParticipantImplementationIdentity, session_id: str) -> None:
        self.implementation = implementation
        self.session_id = session_id
        self.closed = False

    def checkpoint(self):
        return b"remote"

    def restore(self, payload):
        assert isinstance(payload, bytes)

    def close(self):
        self.closed = True


class RemoteRobotProxy:
    implementation_identity = ParticipantImplementationIdentity(
        "robot", "remote-arm", "7", "robot-abi", "robot-schema", "d" * 64
    )
    runtime_identity = runtime_identity_for_test("robot")

    def open_session(self, *, session_id: str, services: object):
        del services
        return RemoteSessionProxy(self.implementation_identity, session_id)


class RemoteResolver:
    """Execution-side resolver with no implementation catalog/factory dependency."""

    def __init__(self, endpoint: object) -> None:
        self.endpoint = endpoint
        self.calls: list[ParticipantRuntimeBinding] = []

    def resolve(self, binding: ParticipantRuntimeBinding) -> ParticipantRuntimeHandle:
        self.calls.append(binding)
        return ParticipantRuntimeHandle(binding, self.endpoint)


class NoOpTrialProtocol:
    protocol_id = "remote-noop.v1"
    surface_id = "empty.operations.v1"
    configuration_digest = "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"

    def run(self, operations, context, *, task, input_kind, input_payload):
        del operations, input_kind
        return TrialCycleExecution(str(task), input_payload, context, ())


def test_runtime_resolver_and_bound_endpoint_use_typed_runtime_contracts():
    handle_hints = get_type_hints(ParticipantRuntimeHandle)
    resolver_hints = get_type_hints(ParticipantBindingResolverPort.resolve)
    endpoint_hints = get_type_hints(BoundParticipant.endpoint.fget)

    assert handle_hints["endpoint"] is ParticipantRuntimeEndpoint
    assert resolver_hints["return"] is ParticipantRuntimeHandle
    assert endpoint_hints["return"] is ParticipantRuntimeEndpoint


def test_study_can_run_remote_endpoint_without_local_implementation_catalog():
    resolver = RemoteResolver(RemoteRobotProxy())
    implementation = RemoteRobotProxy.implementation_identity
    spec = ExperimentSpec(
        experiment_id="remote-experiment",
        study_id="remote-study",
        project_id="default-project",
        participants=(ExperimentParticipantSpec("arm", implementation, runtime_identity_for_test("robot"), "a" * 64),),
        model_roles=(model_role_for_test(),),
        workload_digest="c" * 64,
        seed_digest="d" * 64,
        repetitions=1,
        trial_protocol_id="remote-noop.v1",
        trial_protocol_configuration_digest="44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    )
    runtime = build_experiment_runtime(
        participant_adapters=(generic_participant_adapter("robot", resolver),),
        trial_protocol=NoOpTrialProtocol(),
        workflow_surface_factories=(EmptyWorkflowSurfaceFactory(),),
    )

    result = runtime.execute_cycle(spec, task="remote", input_payload={"target": 1})

    assert result.primary_result == {"target": 1}
    assert len(resolver.calls) == 1
    assert resolver.calls[0] == spec.participants[0].runtime_binding()
    assert any("robot.resolve:arm" in row.operation_id for row in result.operation_results)


def test_formal_launch_manifests_reject_unfrozen_implementation_artifacts():
    implementation = ParticipantImplementationIdentity("robot", "arm", "1", "abi", "schema", None)
    binding = ParticipantRuntimeBinding("arm", implementation, runtime_identity_for_test("robot"), "cfg")

    with pytest.raises(ValueError, match="artifact digests"):
        frozen_runtime_manifest(participant_bindings=(binding,))
    with pytest.raises(ValueError, match="artifact digests"):
        run_launch_manifest(participant_bindings=(binding,))
