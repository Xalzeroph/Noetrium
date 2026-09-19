from __future__ import annotations

from tests_support import FakeParticipantResolver, participant, model_role_for_test
from tests_support import agent_turn_runtime

import hashlib

from noetrium_platform.capabilities.participant.agent.api import AgentIdentity, AgentSnapshot, AgentTurnResult
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityProviderIdentity,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.foundation.kernel.kernel import EffectClass, canonical_digest
from noetrium_platform.research.execution.workflow.implementations.agent_turn import AGENT_TURN_TRIAL_CONFIGURATION_DIGEST
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentParticipantSpec, ExperimentSpec


class EchoProviderSession:
    def __init__(self):
        self.calls = 0

    @property
    def capabilities(self):
        return (CapabilityDescriptor("echo", "1", "echo.req.v1", "echo.res.v1", EffectClass.PURE, True),)

    def invoke(self, request: CapabilityRequest):
        self.calls += 1
        return CapabilityResult("echo", {"echo": request.payload, "provider_calls": self.calls})

    def checkpoint(self): return str(self.calls).encode()
    def restore(self, payload): self.calls = int(payload.decode())
    def close(self): pass


class EchoProvider:
    identity = CapabilityProviderIdentity("echo-provider", "1", "1", "1", "d" * 64)
    def open_session(self, *, session_id: str, services: object): return EchoProviderSession()


class GenericAgentSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.generation = 0

    def run_turn(self, request, capabilities):
        result = capabilities.invoke(CapabilityRequest(
            "echo", {"task": request.task, "input": request.input_payload}, request.context
        ))
        self.generation += 1
        return AgentTurnResult(result.payload, f"agent-g{self.generation}")

    def checkpoint(self):
        payload = str(self.generation).encode()
        return AgentSnapshot("generic-agent", "1", "1", self.session_id, hashlib.sha256(payload).hexdigest(), payload)

    def restore(self, snapshot): self.generation = int(snapshot.opaque_payload.decode())
    def diagnostics(self): return {"generation": self.generation}
    def close(self): pass


class GenericAgent:
    identity = AgentIdentity("generic-agent", "1", "1", "1", "a" * 64)
    def open_session(self, *, session_id: str, services: object): return GenericAgentSession(session_id)


def _spec():
    return ExperimentSpec(
        experiment_id="agent-only",
        study_id="default-study",
        project_id="default-project",
        participants=(
            participant("capability_provider", "echo", "echo-provider", implementation_version="1", abi_version="1", schema_version="1", artifact_digest="d" * 64),
            participant("agent", "agent", "generic-agent", implementation_version="1", abi_version="1", schema_version="1", artifact_digest="a" * 64, depends_on_roles=("echo",)),
        ),
        model_roles=(model_role_for_test(),), workload_digest="b" * 64,
        seed_digest="c" * 64, repetitions=1, trial_protocol_id="agent_turn.v2",
        trial_protocol_configuration_digest=AGENT_TURN_TRIAL_CONFIGURATION_DIGEST,
    )


def _runtime(checkpoint_store=None):
    agents = FakeParticipantResolver(); agents.register("agent", "generic-agent", GenericAgent)
    providers = FakeParticipantResolver(); providers.register("capability_provider", "echo-provider", EchoProvider)
    return agent_turn_runtime(
        agents,
        capability_plugins=providers,
        checkpoint_store=checkpoint_store,
    )


def test_agent_only_study_has_no_method_or_environment_dependency():
    result = _runtime().execute_cycle(
        _spec(), task="hello", input_payload={"x": 1}
    )
    assert "hello" in result.context_text
    operation_ids = [row.operation_id for row in result.operation_results]
    assert not any("method.resolve" in row for row in operation_ids)
    assert not any("environment.resolve" in row for row in operation_ids)
    assert any("agent.resolve" in row for row in operation_ids)
    assert any("capability_provider.resolve" in row for row in operation_ids)
    assert any("capability.invoke" in row for row in operation_ids)
    assert any("agent.run_turn" in row for row in operation_ids)


def test_agent_only_long_run_keeps_agent_session_alive_across_cycles():
    runtime = _runtime()
    run = runtime.open_run(_spec())
    try:
        # long-run cycle identity must belong to open run; create using its stable ids
        from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
        c1 = DecisionCycleIdentity(run.identity.run_id, "dc1", run.identity.session_id, "task1", run.identity.trace_id)
        c2 = DecisionCycleIdentity(run.identity.run_id, "dc2", run.identity.session_id, "task2", run.identity.trace_id)
        r1 = run.execute(task="one", input_kind="input", input_payload=1, cycle_identity=c1)
        r2 = run.execute(task="two", input_kind="input", input_payload=2, cycle_identity=c2)
        assert r1.primary_result.agent_generation == "agent-g1"
        assert r2.primary_result.agent_generation == "agent-g2"
    finally:
        run.close()


def test_agent_only_joint_checkpoint_restores_agent_and_provider_state(tmp_path):
    from noetrium_platform.research.experimentation.checkpoint.providers.directory_store import DirectoryRunCheckpointStore
    from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
    from noetrium_platform.research.experimentation.run.identity.api import RunIdentity

    store = DirectoryRunCheckpointStore(tmp_path / "checkpoints")
    runtime = _runtime(store)
    identity = RunIdentity("run-agent", "session-agent", "trace-agent")
    cycle1 = DecisionCycleIdentity("run-agent", "dc1", "session-agent", "task1", "trace-agent")
    with runtime.open_run(_spec(), run_identity=identity) as run:
        first = run.execute(task="one", input_kind="input", input_payload=1, cycle_identity=cycle1)
        checkpoint_id = run.latest_checkpoint_id
        assert checkpoint_id is not None
        assert first.primary_result.agent_generation == "agent-g1"
        assert first.primary_result.output["provider_calls"] == 1

    runtime2 = _runtime(store)
    restored = runtime2.open_run(
        _spec(),
        run_identity=identity,
        restore_checkpoint_id=checkpoint_id,
        restore_cycle_identity=cycle1,
    )
    try:
        cycle2 = DecisionCycleIdentity("run-agent", "dc2", "session-agent", "task2", "trace-agent")
        second = restored.execute(task="two", input_kind="input", input_payload=2, cycle_identity=cycle2)
        assert second.primary_result.agent_generation == "agent-g2"
        assert second.primary_result.output["provider_calls"] == 2
    finally:
        restored.close()
