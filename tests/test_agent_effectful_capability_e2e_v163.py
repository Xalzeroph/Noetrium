from __future__ import annotations

from tests_support import model_role_for_test

from tests_support import FakeParticipantResolver, participant
from tests_support import agent_turn_runtime

import hashlib

from noetrium_platform.capabilities.participant.agent.api import AgentIdentity, AgentSnapshot, AgentTurnResult
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityEffectReconciliationResult,
    CapabilityProviderIdentity,
    CapabilityRequest,
    CapabilityResult,
    capability_effect_request_id,
    capability_request_digest,
)
from noetrium_platform.infrastructure.reliability.effect.api import EffectReconciliationDisposition, PreparedEffectHandle
from noetrium_platform.infrastructure.reliability.effect.runtime import InMemoryEffectIntentJournal
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt, canonical_digest
from noetrium_platform.research.execution.workflow.implementations.agent_turn import AGENT_TURN_TRIAL_CONFIGURATION_DIGEST
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentParticipantSpec, ExperimentSpec


class WriteToolSession:
    effect_recovery_durability = "crash_durable"
    execute_calls = 0
    reconcile_calls = 0

    @property
    def capabilities(self):
        return (
            CapabilityDescriptor(
                "tool.write", "1", "tool.write.req.v1", "tool.write.res.v1",
                EffectClass.NON_IDEMPOTENT,
            ),
        )

    def prepare_capability_effect(self, request):
        return PreparedEffectHandle.build(
            request_id=capability_effect_request_id(request),
            request_digest=capability_request_digest(request),
            provider_schema="write-tool.recovery.v1",
            opaque_payload=b"write-token-1",
            provider_instance_id="write-tool-instance",
        )

    @staticmethod
    def _result(digest):
        return CapabilityResult(
            "tool.write", {"ok": True},
            effect=EffectReceipt(
                "write-effect-1", digest, EffectClass.NON_IDEMPOTENT,
                EffectCertainty.EFFECT_CONFIRMED, "write-tool-instance",
            ),
        )

    def execute_prepared_capability(self, request, handle):
        type(self).execute_calls += 1
        return self._result(handle.request_digest)

    def reconcile_prepared_capability(self, handle, context):
        del context
        type(self).reconcile_calls += 1
        return CapabilityEffectReconciliationResult(
            "tool.write", EffectReconciliationDisposition.APPLIED,
            self._result(handle.request_digest),
        )

    def invoke(self, request):
        raise AssertionError("raw invoke must not be used for non-idempotent capability")

    def checkpoint(self): return b"provider"
    def restore(self, payload): del payload
    def close(self): pass


class WriteToolProvider:
    identity = CapabilityProviderIdentity("write-tool", "1", "1", "1", "e" * 64)
    def open_session(self, *, session_id: str, services: object):
        del session_id, services
        return WriteToolSession()


class ToolAgentSession:
    def __init__(self, session_id):
        self.session_id = session_id
        self.generation = 0

    def run_turn(self, request, capabilities):
        result = capabilities.invoke(CapabilityRequest(
            "tool.write",
            {"task": request.task, "payload": request.input_payload},
            request.context,
            "stable-write-slot",
        ))
        self.generation += 1
        return AgentTurnResult(result.payload, f"agent-g{self.generation}")

    def checkpoint(self):
        payload = str(self.generation).encode()
        return AgentSnapshot(
            "tool-agent", "1", "1", self.session_id,
            hashlib.sha256(payload).hexdigest(), payload,
        )

    def restore(self, snapshot): self.generation = int(snapshot.opaque_payload.decode())
    def diagnostics(self): return {"generation": self.generation}
    def close(self): pass


class ToolAgent:
    identity = AgentIdentity("tool-agent", "1", "1", "1", "a" * 64)
    def open_session(self, *, session_id: str, services: object):
        del services
        return ToolAgentSession(session_id)


def _spec():
    return ExperimentSpec(
        experiment_id="agent-effectful",
        study_id="default-study",
        project_id="default-project",
        participants=(
            participant("capability_provider", "writer", "write-tool", implementation_version="1", abi_version="1", schema_version="1", artifact_digest="e" * 64),
            participant("agent", "agent", "tool-agent", implementation_version="1", abi_version="1", schema_version="1", artifact_digest="a" * 64, depends_on_roles=("writer",)),
        ),
        model_roles=(model_role_for_test(),), workload_digest="b" * 64,
        seed_digest="c" * 64, repetitions=1, trial_protocol_id="agent_turn.v2",
        trial_protocol_configuration_digest=AGENT_TURN_TRIAL_CONFIGURATION_DIGEST,
    )


def _runtime(journal):
    agents = FakeParticipantResolver(); agents.register("agent", "tool-agent", ToolAgent)
    providers = FakeParticipantResolver(); providers.register("capability_provider", "write-tool", WriteToolProvider)
    return agent_turn_runtime(
        agents,
        capability_plugins=providers,
        effect_journal=journal,
    )


def test_agent_only_non_idempotent_tool_replay_does_not_repeat_external_effect():
    WriteToolSession.execute_calls = WriteToolSession.reconcile_calls = 0
    journal = InMemoryEffectIntentJournal()
    runtime = _runtime(journal)
    cycle = DecisionCycleIdentity("run", "dc", "session", "task", "trace")

    first = runtime.execute_cycle(
        _spec(), task="write", input_payload={"value": 1}, cycle_identity=cycle
    )
    second = runtime.execute_cycle(
        _spec(), task="write", input_payload={"value": 1}, cycle_identity=cycle
    )

    assert first.primary_result.output == second.primary_result.output == {"ok": True}
    assert WriteToolSession.execute_calls == 1
    assert WriteToolSession.reconcile_calls == 1
    second_ids = [row.operation_id for row in second.operation_results]
    assert any("capability.effect.reconcile:" in row for row in second_ids)
    assert not any("capability.effect.prepare:" in row for row in second_ids)
    assert not any("capability.invoke:tool.write:key:" in row for row in second_ids)
