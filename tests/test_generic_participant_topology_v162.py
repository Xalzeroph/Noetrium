from __future__ import annotations
from noetrium_platform.composition.experiment_runtime import build_experiment_runtime
from tests_support import participant, model_role_for_test

from dataclasses import replace

from noetrium_platform.foundation.kernel.kernel import ComponentIdentity
from noetrium_platform.capabilities.participant.core.api.checkpoint import ParticipantCheckpoint
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantRuntimeHandle
from noetrium_platform.research.experimentation.checkpoint.providers.directory_store import DirectoryRunCheckpointStore
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentParticipantTopology
from noetrium_platform.research.execution.workflow.api import TrialCycleExecution
from noetrium_platform.research.experimentation.experiment.api import ExperimentParticipantSpec, ExperimentSpec


class SidecarPlugin:
    pass


class SidecarSession:
    restore_payloads: list[bytes] = []
    opens = 0
    closes = 0

    def __init__(self):
        SidecarSession.opens += 1
        self.state = b"sidecar-state"

    def close(self):
        SidecarSession.closes += 1


class SidecarAdapter:
    kind = "sidecar"

    @staticmethod
    def _component(binding):
        impl = binding.implementation
        return ComponentIdentity(
            f"participant.{binding.role}", impl.digest(),
            impl.implementation_version, impl.schema_version,
            binding.configuration_digest or "default",
        )

    def frozen_component(self, binding): return self._component(binding)
    def resolve(self, binding): return ParticipantRuntimeHandle(binding, SidecarPlugin())
    def actual_component(self, participant):
        binding = participant.binding; impl = binding.implementation
        return ComponentIdentity(
            f"participant.{binding.role}", impl.digest(),
            impl.implementation_version, impl.schema_version,
            binding.configuration_digest or "default",
        )

    def validate(self, binding, participant):
        assert participant.binding == binding

    def open_session(self, participant, *, session_id, services): return SidecarSession()
    def close_session(self, session): session.close()
    def checkpoint(self, participant, session, *, session_id):
        return ParticipantCheckpoint.capture(
            binding=participant.binding, component=self.actual_component(participant),
            session_id=session_id, opaque_payload=session.state,
        )

    def restore(self, participant, session, checkpoint, *, session_id):
        checkpoint.verify(
            binding=participant.binding, component=self.actual_component(participant), session_id=session_id
        )
        SidecarSession.restore_payloads.append(checkpoint.opaque_payload)
        session.state = checkpoint.opaque_payload


class NoOpTrialProtocol:
    protocol_id = "no_op.v1"
    surface_id = "empty.operations.v1"
    configuration_digest = "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"

    def run(self, operations, context, *, task, input_kind, input_payload):
        del operations, input_kind
        return TrialCycleExecution(str(task), {"input": input_payload}, context, ())


def spec():
    return ExperimentSpec(
        experiment_id="custom-study",
        study_id="default-study",
        project_id="default-project",
        participants=(participant("sidecar", "controller", "custom", implementation_version="1", abi_version="1", schema_version="1", configuration_digest="cfg"),),
        model_roles=(model_role_for_test(),), workload_digest="b" * 64,
        seed_digest="c" * 64, repetitions=1, trial_protocol_id="no_op.v1",
        trial_protocol_configuration_digest="44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    )


def runtime(store=None):
    from tests_support import EmptyWorkflowSurfaceFactory
    return build_experiment_runtime(
        trial_protocol=NoOpTrialProtocol(),
        participant_adapters=(SidecarAdapter(),),
        checkpoint_store=store,
        workflow_surface_factories=(EmptyWorkflowSurfaceFactory(),),
    )


def test_custom_participant_runs_without_method_environment_or_agent():
    SidecarSession.opens = SidecarSession.closes = 0
    result = runtime().execute_cycle(spec(), task="hello", input_payload={"x": 1})
    assert result.context_text == "hello"
    assert result.primary_result == {"input": {"x": 1}}
    assert SidecarSession.opens == 1
    assert SidecarSession.closes == 1
    ids = [row.operation_id for row in result.operation_results]
    assert any("sidecar.resolve:controller" in row for row in ids)
    assert any("sidecar.open_session:controller" in row for row in ids)
    assert any("sidecar.close:controller" in row for row in ids)


def test_custom_participant_checkpoint_restore_needs_no_runtime_core_change(tmp_path):
    SidecarSession.restore_payloads.clear()
    store = DirectoryRunCheckpointStore(tmp_path / "cp")
    identity = RunIdentity("run", "session", "trace")
    cycle1 = DecisionCycleIdentity("run", "dc1", "session", "task1", "trace")
    with runtime(store).open_run(spec(), run_identity=identity) as run:
        run.execute(task="one", input_payload=1, cycle_identity=cycle1)
        checkpoint_id = run.latest_checkpoint_id
    assert checkpoint_id

    restored = runtime(store).open_run(
        spec(), run_identity=identity,
        restore_checkpoint_id=checkpoint_id,
        restore_cycle_identity=cycle1,
    )
    restored.close()
    assert SidecarSession.restore_payloads == [b"sidecar-state"]


class DependencyPlugin:
    def __init__(self, role: str) -> None:
        self.role = role


class DependencySession:
    events: list[str] = []

    def __init__(self, role: str) -> None:
        self.role = role
        self.events.append(f"open:{role}")

    def close(self) -> None:
        self.events.append(f"close:{self.role}")


class DependencyAdapter:
    kind = "dependency"
    resolves = 0

    @staticmethod
    def _component(binding):
        impl = binding.implementation
        return ComponentIdentity(
            f"participant.{binding.role}", impl.digest(),
            impl.implementation_version, impl.schema_version,
            binding.configuration_digest or "default",
        )

    def frozen_component(self, binding): return self._component(binding)

    def resolve(self, binding):
        type(self).resolves += 1
        return ParticipantRuntimeHandle(binding, DependencyPlugin(binding.role))

    def actual_component(self, participant): return self._component(participant.binding)

    def validate(self, binding, participant):
        assert participant.binding == binding
        assert participant.endpoint.role == binding.role

    def open_session(self, participant, *, session_id, services):
        del session_id, services
        return DependencySession(participant.endpoint.role)

    def close_session(self, session): session.close()

    def checkpoint(self, participant, session, *, session_id):
        del session
        return ParticipantCheckpoint.capture(
            binding=participant.binding, component=self.actual_component(participant),
            session_id=session_id, opaque_payload=b"dependency",
        )

    def restore(self, participant, session, checkpoint, *, session_id):
        del session
        checkpoint.verify(
            binding=participant.binding, component=self.actual_component(participant), session_id=session_id
        )


def _dependency_spec(*participants: ExperimentParticipantSpec) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id="dependency-study",
        study_id="default-study",
        project_id="default-project", participants=participants, model_roles=(model_role_for_test(),),
        workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1,
        trial_protocol_id="no_op.v1",
        trial_protocol_configuration_digest="44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    )


def _dependency_runtime() -> ExperimentRuntime:
    from tests_support import EmptyWorkflowSurfaceFactory
    return build_experiment_runtime(
        trial_protocol=NoOpTrialProtocol(), participant_adapters=(DependencyAdapter(),),
        workflow_surface_factories=(EmptyWorkflowSurfaceFactory(),),
    )


def test_missing_participant_dependency_fails_before_any_resolve_side_effect():
    DependencyAdapter.resolves = 0
    bad = _dependency_spec(
        participant("dependency", "upper", "upper", depends_on_roles=("missing",)),
    )
    try:
        _dependency_runtime().execute_cycle(bad, task="x", input_payload=None)
    except ValueError as exc:
        assert "missing dependencies" in str(exc)
    else:
        raise AssertionError("missing participant dependency must fail closed")
    assert DependencyAdapter.resolves == 0


def test_participant_dependency_cycle_fails_before_any_resolve_side_effect():
    DependencyAdapter.resolves = 0
    bad = _dependency_spec(
        participant("dependency", "a", "a", depends_on_roles=("b",)),
        participant("dependency", "b", "b", depends_on_roles=("a",)),
    )
    try:
        _dependency_runtime().execute_cycle(bad, task="x", input_payload=None)
    except ValueError as exc:
        assert "dependency cycle" in str(exc)
    else:
        raise AssertionError("participant dependency cycle must fail closed")
    assert DependencyAdapter.resolves == 0


def test_participants_open_in_topology_order_and_close_in_exact_reverse_order():
    DependencyAdapter.resolves = 0
    DependencySession.events.clear()
    good = _dependency_spec(
        participant("dependency", "base", "base"),
        participant("dependency", "middle", "middle", depends_on_roles=("base",)),
        participant("dependency", "top", "top", depends_on_roles=("middle",)),
    )
    _dependency_runtime().execute_cycle(good, task="x", input_payload=None)
    assert DependencySession.events == [
        "open:base", "open:middle", "open:top",
        "close:top", "close:middle", "close:base",
    ]


def test_participant_kind_rejects_operation_namespace_injection_before_resolve():
    DependencyAdapter.resolves = 0
    import pytest
    with pytest.raises(ValueError, match="safe operation namespace token"):
        participant("dependency.evil", "evil", "evil")
    assert DependencyAdapter.resolves == 0


def test_participant_topology_preserves_declared_order_within_dependency_waves():
    graph = _dependency_spec(
        participant("dependency", "child", "child", depends_on_roles=("root-x",)),
        participant("dependency", "root-x", "root-x"),
        participant("dependency", "root-y", "root-y"),
    )
    ordered = ExperimentParticipantTopology.from_spec(graph).ordered()
    assert tuple(row.role for row in ordered) == ("root-x", "root-y", "child")
