from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityEffectReconciliationResult,
    CapabilityRequest,
    CapabilityResult,
    capability_effect_request_id,
    capability_request_digest,
)
from noetrium_platform.infrastructure.reliability.effect.api import EffectReconciliationDisposition, PreparedEffectHandle
from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectCompletionEvidence,
    EffectIntent,
    EffectIntentPhase,
)
from noetrium_platform.infrastructure.reliability.effect.runtime import (
    InMemoryEffectIntentJournal,
    SQLiteEffectIntentJournal,
)
from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    InMemoryMachineJournal,
    OperationExecutor,
)
from noetrium_platform.research.execution.workflow.implementations.agent_turn.capability_effects import CapabilityEffectExecutor
from noetrium_platform.research.execution.workflow.implementations.agent_turn.capability_effect_contracts import UnsafeEffectfulCapability
from noetrium_platform.research.execution.workflow.implementations.agent_turn.capability_operations import CapabilityOperationAdapter
from noetrium_platform.research.execution.workflow.implementations.agent_turn.capability_routing import (
    CapabilitySessionBinding,
    StudyCapabilityRouter,
    UnsafeGenericCapability,
)
from noetrium_platform.research.execution.capability.runtime import (
    CapabilityInvocationPipelineFactory,
    ScopedRegistrationRuntime,
)
from noetrium_platform.research.execution.workflow.runtime import EffectIntentOperations, KernelOperationDispatcher


class EffectfulSession:
    capabilities = (
        CapabilityDescriptor(
            "tool.write", "1", "tool.write.request.v1", "tool.write.result.v1",
            effect_class=EffectClass.NON_IDEMPOTENT,
        ),
    )
    effect_recovery_durability = "crash_durable"
    prepare_calls = 0
    execute_calls = 0
    reconcile_calls = 0

    def prepare_capability_effect(self, request):
        type(self).prepare_calls += 1
        return PreparedEffectHandle.build(
            request_id=capability_effect_request_id(request),
            request_digest=capability_request_digest(request),
            provider_schema="tool.write.recovery.v1",
            opaque_payload=b"provider-private-token",
            provider_instance_id="writer-1",
        )

    @staticmethod
    def _result(request_digest: str):
        return CapabilityResult(
            "tool.write",
            {"written": True},
            effect=EffectReceipt(
                "effect:write-1",
                request_digest,
                EffectClass.NON_IDEMPOTENT,
                EffectCertainty.EFFECT_CONFIRMED,
                "writer-1",
            ),
        )

    def execute_prepared_capability(self, request, handle):
        type(self).execute_calls += 1
        assert handle.request_digest == capability_request_digest(request)
        return self._result(handle.request_digest)

    def reconcile_prepared_capability(self, handle, context):
        del context
        type(self).reconcile_calls += 1
        return CapabilityEffectReconciliationResult(
            "tool.write",
            EffectReconciliationDisposition.APPLIED,
            self._result(handle.request_digest),
        )

    # Generic provider compatibility methods unused for the effectful route.
    def invoke(self, request):
        raise AssertionError("effectful route must not call raw session.invoke")

    def checkpoint(self): return b""
    def restore(self, payload): del payload
    def close(self): pass


class Provider:
    pass


def _context():
    return ExecutionContext(
        "run", "trace", "span", study_id="study", lifetime_id="life",
        task_id="task", decision_cycle_id="dc", checkpoint_id="cp1",
        participant_generations=(("agent", "agent-g1"),),
    )


def _router(journal=None):
    dispatcher = KernelOperationDispatcher(OperationExecutor())
    operations = CapabilityOperationAdapter(dispatcher)
    component = ComponentIdentity("capability_provider.writer", "writer", "1", "1", "cfg")
    session = EffectfulSession()
    binding = CapabilitySessionBinding(component, session, "writer")
    effect_executor = (
        CapabilityEffectExecutor(dispatcher, EffectIntentOperations(dispatcher, journal), operations)
        if journal is not None else None
    )
    consumer = ComponentIdentity("agent.generic", "agent", "1", "1", "agent-cfg")
    return StudyCapabilityRouter(
        operations,
        (binding,),
        effect_executor=effect_executor,
        consumer_component=consumer,
        pipeline=CapabilityInvocationPipelineFactory(InMemoryMachineJournal()).create(),
        scope=ScopedRegistrationRuntime("test-capability-router"),
    ), session


def test_effectful_capability_is_exactly_once_for_same_logical_key():
    EffectfulSession.prepare_calls = EffectfulSession.execute_calls = EffectfulSession.reconcile_calls = 0
    journal = InMemoryEffectIntentJournal()
    router, _ = _router(journal)
    request = CapabilityRequest("tool.write", {"value": 7}, _context(), "write-slot-1")

    first = router.invoke(request)
    second = router.invoke(request)

    assert first.payload == second.payload == {"written": True}
    assert EffectfulSession.prepare_calls == 1
    assert EffectfulSession.execute_calls == 1
    assert EffectfulSession.reconcile_calls == 1
    operations = router.drain_operations()
    assert any(row.operation_id.startswith("dc:capability.effect.prepare:") for row in operations)
    assert sum("capability.invoke:tool.write:key:" in row.operation_id for row in operations) == 1
    assert any("capability.effect.reconcile:" in row.operation_id for row in operations)


def test_effectful_capability_without_journal_fails_before_provider_side_effect():
    EffectfulSession.prepare_calls = EffectfulSession.execute_calls = 0
    router, _ = _router(None)
    with pytest.raises(UnsafeGenericCapability):
        router.invoke(CapabilityRequest("tool.write", {"value": 7}, _context(), "slot"))
    assert EffectfulSession.prepare_calls == 0
    assert EffectfulSession.execute_calls == 0


def test_effectful_capability_requires_stable_idempotency_key_before_prepare():
    EffectfulSession.prepare_calls = EffectfulSession.execute_calls = 0
    router, _ = _router(InMemoryEffectIntentJournal())
    with pytest.raises(UnsafeEffectfulCapability):
        router.invoke(CapabilityRequest("tool.write", {"value": 7}, _context()))
    assert EffectfulSession.prepare_calls == 0
    assert EffectfulSession.execute_calls == 0


def test_generic_effect_journal_sqlite_reopens_without_environment_types():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "effects.sqlite3"
        context = _context()
        provider = ComponentIdentity("capability_provider.writer", "writer", "1", "1", "cfg")
        request = CapabilityRequest("tool.write", {"value": 9}, context, "slot-9")
        digest = capability_request_digest(request)
        handle = PreparedEffectHandle.build(
            request_id=capability_effect_request_id(request),
            request_digest=digest,
            provider_schema="writer.recovery.v1",
            opaque_payload=b"opaque",
        )
        intent = EffectIntent.build(
            request_id=handle.request_id,
            request_digest=digest,
            operation_id="dc:capability.invoke:tool.write:key:x",
            provider_component=provider,
            context=context,
            recovery_handle=handle,
            intent_namespace="capability-effect-intent",
        )
        first = SQLiteEffectIntentJournal(path)
        first.prepare(intent)
        second = SQLiteEffectIntentJournal(path)
        reopened = second.load(intent.intent_id)
        assert reopened is not None
        assert reopened.phase is EffectIntentPhase.PREPARED
        assert reopened.intent.request_id == handle.request_id
        assert reopened.intent.provider_component_digest == intent.provider_component_digest
        assert reopened.intent.recovery_handle is not None
        assert reopened.intent.recovery_handle.opaque_payload == b"opaque"
