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
    capability_descriptor_minimum_execution_seconds,
    capability_request_minimum_execution_seconds,
    capability_request_digest,
)
from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectIntentPhase,
    EffectReconciliationDisposition,
    build_effect_intent,
    intent_field,
    prepared_effect_handle,
    prepared_handle_field,
    record_field,
)
from noetrium_platform.infrastructure.reliability.effect.runtime import (
    memory_effect_intent_journal,
    sqlite_effect_intent_journal,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    TaskDeadlineExceeded,
    UNBOUNDED_EXECUTION_CONTROL,
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
from noetrium_platform.composition.workflows.agent_turn.capability_effects import CapabilityEffectExecutor
from noetrium_platform.composition.workflows.agent_turn.capability_effects import UnsafeEffectfulCapability
from noetrium_platform.composition.workflows.agent_turn.runtime import CapabilityOperationAdapter
from noetrium_platform.composition.workflows.agent_turn.runtime import (
    CapabilitySessionBinding,
    StudyCapabilityRouter,
    UnsafeGenericCapability,
)
from noetrium_platform.research.execution.capability.runtime import (
    CapabilityInvocationPipelineFactory,
    ScopedRegistrationRuntime,
)
from noetrium_platform.research.execution.workflow.runtime import (
    DurableKernelOperationDispatcher,
    EffectIntentOperations,
    KernelOperationDispatcher,
)
from noetrium_platform.research.execution.operation.command.providers import SQLiteCommandStore
from noetrium_platform.research.execution.operation.command.runtime import CommandIntentOwner
from noetrium_platform.research.execution.operation.providers import SQLiteOperationStore
from noetrium_platform.research.execution.operation.runtime import OperationOwner


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

    def prepare_capability_effect(self, request, control):
        control.checkpoint()
        type(self).prepare_calls += 1
        return prepared_effect_handle(
            request_id=capability_effect_request_id(request),
            request_digest=capability_request_digest(request),
            provider_schema="tool.write.recovery.v1",
            opaque_payload=b"provider-private-token",
            provider_instance_id="writer-1",
        )

    @staticmethod
    def _result(request_id: str, request_digest: str):
        return CapabilityResult(
            "tool.write",
            {"written": True},
            effect=EffectReceipt(
                request_id,
                request_digest,
                EffectClass.NON_IDEMPOTENT,
                EffectCertainty.EFFECT_CONFIRMED,
                "writer-1",
            ),
        )

    def execute_prepared_capability(self, request, handle, control):
        control.checkpoint()
        type(self).execute_calls += 1
        assert str(prepared_handle_field(handle, "request_digest")) == capability_request_digest(request)
        return self._result(str(prepared_handle_field(handle, "request_id")), str(prepared_handle_field(handle, "request_digest")))

    def reconcile_prepared_capability(self, handle, context, control):
        del context
        control.checkpoint()
        type(self).reconcile_calls += 1
        return CapabilityEffectReconciliationResult(
            "tool.write",
            EffectReconciliationDisposition.APPLIED,
            self._result(str(prepared_handle_field(handle, "request_id")), str(prepared_handle_field(handle, "request_digest"))),
        )

    # Generic provider compatibility methods unused for the effectful route.
    def invoke(self, request):
        raise AssertionError("effectful route must not call raw session.invoke")

    def checkpoint(self): return b""
    def restore(self, payload): del payload
    def close(self): pass


class InitiallyUncertainEffectfulSession(EffectfulSession):
    execute_calls = 0
    reconcile_calls = 0

    @staticmethod
    def _uncertain_result(request_id: str, request_digest: str):
        return CapabilityResult(
            "tool.write",
            {"written": True},
            effect=EffectReceipt(
                request_id,
                request_digest,
                EffectClass.NON_IDEMPOTENT,
                EffectCertainty.INDETERMINATE,
                "writer-1",
            ),
        )

    def execute_prepared_capability(self, request, handle, control):
        control.checkpoint()
        type(self).execute_calls += 1
        assert str(prepared_handle_field(handle, "request_digest")) == capability_request_digest(request)
        return self._uncertain_result(str(prepared_handle_field(handle, "request_id")), str(prepared_handle_field(handle, "request_digest")))

    def reconcile_prepared_capability(self, handle, context, control):
        del context
        control.checkpoint()
        type(self).reconcile_calls += 1
        return CapabilityEffectReconciliationResult(
            "tool.write",
            EffectReconciliationDisposition.APPLIED,
            EffectfulSession._result(str(prepared_handle_field(handle, "request_id")), str(prepared_handle_field(handle, "request_digest"))),
        )




class BudgetedEffectfulSession(EffectfulSession):
    capabilities = (
        CapabilityDescriptor(
            "tool.write", "1", "tool.write.request.v1", "tool.write.result.v1",
            effect_class=EffectClass.NON_IDEMPOTENT,
            metadata={"minimum_execution_seconds": 6.001},
        ),
    )
    prepare_calls = 0
    execute_calls = 0
    reconcile_calls = 0


class _FiveSecondControl(type(UNBOUNDED_EXECUTION_CONTROL)):
    @property
    def remaining_seconds(self) -> float:
        return 5.0


class Provider:
    pass


def _context():
    return ExecutionContext(
        "run", "trace", "span", study_id="study", lifetime_id="life",
        task_id="task", decision_cycle_id="dc", checkpoint_id="cp1",
        participant_generations=(("agent", "agent-g1"),),
    )


def _router(journal, root: Path, session_type=EffectfulSession):
    kernel = KernelOperationDispatcher(OperationExecutor())
    commands = CommandIntentOwner(SQLiteCommandStore(root / "commands.sqlite3"))
    operation_owner = OperationOwner(SQLiteOperationStore(root / "operations.sqlite3"))
    dispatcher = DurableKernelOperationDispatcher(
        kernel,
        commands=commands,
        submissions=operation_owner,
        admissions=operation_owner,
        operations=operation_owner,
    )
    operations = CapabilityOperationAdapter(dispatcher)
    component = ComponentIdentity("capability_provider.writer", "writer", "1", "1", "cfg")
    session = session_type()
    binding = CapabilitySessionBinding(component, session, "writer")
    effect_executor = (
        CapabilityEffectExecutor(dispatcher, EffectIntentOperations(journal), operations)
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


def test_capability_execution_minimum_is_conservative_before_mediation_and_exact_after() -> None:
    descriptor = CapabilityDescriptor(
        "tool.write",
        "1",
        "tool.write.request.v1",
        "tool.write.result.v1",
        effect_class=EffectClass.NON_IDEMPOTENT,
        metadata={
            "minimum_execution_seconds": 1.0,
            "action_minimum_execution_seconds": {
                "fast": 2.0,
                "slow": 6.0,
            },
        },
    )
    request = CapabilityRequest(
        "tool.write",
        {"action_type": "fast"},
        _context(),
        "minimum-contract-slot",
    )

    assert capability_descriptor_minimum_execution_seconds(descriptor) == 6.0
    assert capability_request_minimum_execution_seconds(descriptor, request) == 2.0


def test_effectful_capability_is_exactly_once_for_same_logical_key(tmp_path: Path):
    EffectfulSession.prepare_calls = EffectfulSession.execute_calls = EffectfulSession.reconcile_calls = 0
    journal = memory_effect_intent_journal()
    router, _ = _router(journal, tmp_path)
    request = CapabilityRequest("tool.write", {"value": 7}, _context(), "write-slot-1")

    first = router.invoke(request, UNBOUNDED_EXECUTION_CONTROL)
    second = router.invoke(request, UNBOUNDED_EXECUTION_CONTROL)

    assert first.payload == second.payload == {"written": True}
    assert EffectfulSession.prepare_calls == 1
    assert EffectfulSession.execute_calls == 1
    assert EffectfulSession.reconcile_calls == 0
    operations = router.drain_operations()
    assert any(row.operation_id.startswith("dc:capability.effect.prepare:") for row in operations)
    assert sum("capability.invoke:tool.write:key:" in row.operation_id for row in operations) == 1
    assert not any("capability.effect.reconcile:" in row.operation_id for row in operations)


def test_effectful_capability_admission_fails_before_provider_prepare(tmp_path: Path):
    BudgetedEffectfulSession.prepare_calls = 0
    BudgetedEffectfulSession.execute_calls = 0
    BudgetedEffectfulSession.reconcile_calls = 0
    router, _ = _router(
        memory_effect_intent_journal(),
        tmp_path,
        session_type=BudgetedEffectfulSession,
    )
    request = CapabilityRequest("tool.write", {"value": 7}, _context(), "budget-slot")

    with pytest.raises(
        TaskDeadlineExceeded,
        match="capability execution budget cannot contain provider minimum",
    ):
        router.invoke(request, _FiveSecondControl())

    assert BudgetedEffectfulSession.prepare_calls == 0
    assert BudgetedEffectfulSession.execute_calls == 0
    assert BudgetedEffectfulSession.reconcile_calls == 0
    assert router.drain_operations() == ()


def test_existing_effect_replay_bypasses_new_execution_budget_admission(tmp_path: Path):
    BudgetedEffectfulSession.prepare_calls = 0
    BudgetedEffectfulSession.execute_calls = 0
    BudgetedEffectfulSession.reconcile_calls = 0
    router, _ = _router(
        memory_effect_intent_journal(),
        tmp_path,
        session_type=BudgetedEffectfulSession,
    )
    request = CapabilityRequest("tool.write", {"value": 9}, _context(), "budget-replay-slot")

    first = router.invoke(request, UNBOUNDED_EXECUTION_CONTROL)
    second = router.invoke(request, _FiveSecondControl())

    assert second.payload == first.payload
    assert BudgetedEffectfulSession.prepare_calls == 1
    assert BudgetedEffectfulSession.execute_calls == 1
    assert BudgetedEffectfulSession.reconcile_calls == 0


def test_effectful_capability_without_journal_fails_before_provider_side_effect(tmp_path: Path):
    EffectfulSession.prepare_calls = EffectfulSession.execute_calls = 0
    router, _ = _router(None, tmp_path)
    with pytest.raises(RuntimeError, match="UnsafeGenericCapability"):
        router.invoke(CapabilityRequest("tool.write", {"value": 7}, _context(), "slot"), UNBOUNDED_EXECUTION_CONTROL)
    assert EffectfulSession.prepare_calls == 0
    assert EffectfulSession.execute_calls == 0


def test_effectful_capability_requires_stable_idempotency_key_before_prepare(tmp_path: Path):
    EffectfulSession.prepare_calls = EffectfulSession.execute_calls = 0
    router, _ = _router(memory_effect_intent_journal(), tmp_path)
    with pytest.raises(UnsafeEffectfulCapability):
        router.invoke(CapabilityRequest("tool.write", {"value": 7}, _context()), UNBOUNDED_EXECUTION_CONTROL)
    assert EffectfulSession.prepare_calls == 0
    assert EffectfulSession.execute_calls == 0


def test_generic_effect_journal_sqlite_reopens_without_environment_types():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "effects.sqlite3"
        context = _context()
        provider = ComponentIdentity("capability_provider.writer", "writer", "1", "1", "cfg")
        request = CapabilityRequest("tool.write", {"value": 9}, context, "slot-9")
        digest = capability_request_digest(request)
        handle = prepared_effect_handle(
            request_id=capability_effect_request_id(request),
            request_digest=digest,
            provider_schema="writer.recovery.v1",
            opaque_payload=b"opaque",
        )
        intent = build_effect_intent(
            request_id=str(prepared_handle_field(handle, "request_id")),
            request_digest=digest,
            operation_id="dc:capability.invoke:tool.write:key:x",
            provider_component=provider,
            context=context,
            recovery_handle=handle,
            intent_namespace="capability-effect-intent",
        )
        first = sqlite_effect_intent_journal(path)
        first.prepare(intent)
        second = sqlite_effect_intent_journal(path)
        reopened = second.load(str(intent_field(intent, "intent_id")))
        assert reopened is not None
        assert record_field(reopened, "phase") is EffectIntentPhase.PREPARED
        assert intent_field(record_field(reopened, "intent"), "request_id") == str(prepared_handle_field(handle, "request_id"))
        assert intent_field(record_field(reopened, "intent"), "provider_component_digest") == intent_field(intent, "provider_component_digest")
        assert intent_field(record_field(reopened, "intent"), "recovery_handle") is not None
        assert prepared_handle_field(intent_field(record_field(reopened, "intent"), "recovery_handle"), "opaque_payload") == b"opaque"


def test_effectful_capability_terminalizes_provider_indeterminate_without_reconfirmation(
    tmp_path: Path,
):
    InitiallyUncertainEffectfulSession.prepare_calls = 0
    InitiallyUncertainEffectfulSession.execute_calls = 0
    InitiallyUncertainEffectfulSession.reconcile_calls = 0
    router, _ = _router(
        memory_effect_intent_journal(),
        tmp_path,
        session_type=InitiallyUncertainEffectfulSession,
    )
    request = CapabilityRequest(
        "tool.write",
        {"value": 11},
        _context(),
        "write-slot-uncertain",
    )

    first = router.invoke(request, UNBOUNDED_EXECUTION_CONTROL)
    second = router.invoke(request, UNBOUNDED_EXECUTION_CONTROL)

    assert first.effect is not None
    assert second.effect is not None
    assert first.effect.certainty is EffectCertainty.INDETERMINATE
    assert second.effect.certainty is EffectCertainty.INDETERMINATE
    assert first.payload == {"written": True}
    assert second.payload == first.payload
    assert InitiallyUncertainEffectfulSession.prepare_calls == 1
    assert InitiallyUncertainEffectfulSession.execute_calls == 1
    assert InitiallyUncertainEffectfulSession.reconcile_calls == 0
    operations = router.drain_operations()
    assert not any(
        "capability.effect.reconcile:" in row.operation_id
        for row in operations
    )


class CrashAfterPreparedEffectSession(EffectfulSession):
    execute_calls = 0
    reconcile_calls = 0

    def execute_prepared_capability(self, request, handle, control):
        control.checkpoint()
        type(self).execute_calls += 1
        assert str(prepared_handle_field(handle, "request_digest")) == capability_request_digest(request)
        raise RuntimeError("provider transport died after effect intent")

    def reconcile_prepared_capability(self, handle, context, control):
        del context
        control.checkpoint()
        type(self).reconcile_calls += 1
        return CapabilityEffectReconciliationResult(
            "tool.write",
            EffectReconciliationDisposition.APPLIED,
            EffectfulSession._result(str(prepared_handle_field(handle, "request_id")), str(prepared_handle_field(handle, "request_digest"))),
        )


def test_effectful_capability_reconciles_provider_crash_after_prepare(tmp_path: Path):
    CrashAfterPreparedEffectSession.prepare_calls = 0
    CrashAfterPreparedEffectSession.execute_calls = 0
    CrashAfterPreparedEffectSession.reconcile_calls = 0
    router, _ = _router(
        memory_effect_intent_journal(),
        tmp_path,
        session_type=CrashAfterPreparedEffectSession,
    )
    request = CapabilityRequest(
        "tool.write",
        {"value": 13},
        _context(),
        "write-slot-crash-after-prepare",
    )

    result = router.invoke(request, UNBOUNDED_EXECUTION_CONTROL)

    assert result.payload == {"written": True}
    assert result.effect is not None
    assert result.effect.certainty is EffectCertainty.EFFECT_CONFIRMED
    assert CrashAfterPreparedEffectSession.execute_calls == 1
    assert CrashAfterPreparedEffectSession.reconcile_calls == 1
