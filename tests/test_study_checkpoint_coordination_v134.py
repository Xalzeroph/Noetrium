from tests_support import CompositeParticipantResolver, FakeParticipantResolver
from tests_support import context_action_spec, model_role_for_test
from pathlib import Path
import hashlib
import tempfile

import pytest

from noetrium_platform.composition.context_action import context_action_participant_adapters
from noetrium_platform.capabilities.environment.runtime.api import EnvironmentIdentity
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, OperationExecutor
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodSnapshot
from noetrium_platform.research.experimentation.checkpoint.runtime.coordination import RunCheckpointCoordinator, RunCheckpointIdentityMismatch
from noetrium_platform.research.experimentation.checkpoint.providers.directory_store import DirectoryRunCheckpointStore
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentComponentBinder
from noetrium_platform.research.execution.participants import ParticipantCheckpointOperations, ParticipantResolutionOperations
from noetrium_platform.capabilities.participant.session.runtime.checkpoint_runtime import ParticipantCheckpointRuntime
from noetrium_platform.capabilities.participant.core.api.lifecycle import ParticipantLifecycleAdapterRegistry
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.execution.workflow.runtime import WORKFLOW_RUNTIME_IDENTITY, KernelOperationDispatcher
from noetrium_platform.capabilities.participant.core.api import ParticipantSessionBinding


class MS:
    def __init__(self): self.restored=None
    def checkpoint(self):
        payload=b"method-state"
        return MethodSnapshot("m","1","1","","session",hashlib.sha256(payload).hexdigest(),payload)
    def restore(self,snapshot): self.restored=snapshot

class M:
    identity=MethodIdentity("m","1","1","1")
    def open_session(self, *, session_id: str, services: object): raise AssertionError("not used")

class ES:
    def __init__(self): self.restored=None
    def checkpoint(self): return b"env-state"
    def restore(self,payload): self.restored=payload

class E:
    identity=EnvironmentIdentity("e","1","1","1")
    def open_session(self, *, session_id: str, services: object): raise AssertionError("not used")


def bound(dispatcher, spec):
    mr=FakeParticipantResolver(); mr.register("method", "m",M)
    er=FakeParticipantResolver(); er.register("environment", "e",E)
    return ExperimentComponentBinder(ParticipantResolutionOperations(dispatcher, ParticipantLifecycleAdapterRegistry(context_action_participant_adapters(CompositeParticipantResolver(mr, er))))).bind(
        spec,
        ExecutionContext("run","trace","dc",study_id="s",task_id="task",decision_cycle_id="dc"),
    )


def bindings(b, ms, es):
    return (
        ParticipantSessionBinding(b.participant("method"), ms),
        ParticipantSessionBinding(b.participant("environment"), es),
    )


def test_checkpoint_and_restore_are_operation_bounded_and_treatment_bound():
    with tempfile.TemporaryDirectory() as td:
        dispatcher=KernelOperationDispatcher(OperationExecutor(),caller=WORKFLOW_RUNTIME_IDENTITY)
        spec=context_action_spec("s","m","e")
        b=bound(dispatcher, spec); ms=MS(); es=ES()
        coordinator=RunCheckpointCoordinator(
            dispatcher, DirectoryRunCheckpointStore(Path(td)), ParticipantCheckpointOperations(dispatcher, ParticipantCheckpointRuntime())
        )
        ident=DecisionCycleIdentity("run","dc","session","task","trace")
        context=ExecutionContext(
            "run","trace","dc",study_id="s",task_id="task",decision_cycle_id="dc",
            participant_generations=(("method","mg"),("environment","eg")),
        )
        cp=coordinator.checkpoint(
            spec=spec,bound=b,participant_sessions=bindings(b,ms,es),context=context,cycle_identity=ident,
        )
        assert [x.operation_id for x in cp.operation_results] == [
            "dc:method.checkpoint:method","dc:environment.checkpoint:environment","dc:run.checkpoint.publish"
        ]
        ms2=MS(); es2=ES()
        restored=coordinator.restore(
            cp.manifest.checkpoint_id,spec=spec,bound=b,
            participant_sessions=bindings(b,ms2,es2),context=context,cycle_identity=ident,
        )
        assert ms2.restored.opaque_payload == b"method-state"
        assert es2.restored == b"env-state"
        assert [x.operation_id for x in restored.operation_results] == [
            "dc:run.checkpoint.load","dc:method.restore:method","dc:environment.restore:environment"
        ]

        ms3=MS(); es3=ES()
        duplicate_sessions=bindings(b,ms3,es3)
        with pytest.raises(RuntimeError, match="duplicate roles"):
            coordinator.restore(
                cp.manifest.checkpoint_id,spec=spec,bound=b,
                participant_sessions=(duplicate_sessions[0], duplicate_sessions[0], duplicate_sessions[1]),
                context=context,cycle_identity=ident,
            )
        assert ms3.restored is None
        assert es3.restored is None

        changed=context_action_spec("s","m","e",model_roles=(model_role_for_test(model_stack_seed="different-model"),))
        with pytest.raises(Exception) as exc:
            coordinator.restore(
                cp.manifest.checkpoint_id,spec=changed,bound=b,
                participant_sessions=bindings(b,MS(),ES()),context=context,cycle_identity=ident,
            )
        assert isinstance(exc.value.__cause__, RunCheckpointIdentityMismatch)
