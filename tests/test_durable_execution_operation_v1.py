from pathlib import Path
import sqlite3

from noetrium_platform.research.execution.operation.api import CommandId
from noetrium_platform.research.execution.operation.api import (
    EffectId, IllegalOperationTransition, OperationConflict, OperationCorruption, OperationEffectCertainty, OperationEffectProfile,
    OperationFailure, OperationFailureKind, OperationId, OperationSnapshot, OperationState,
)
from noetrium_platform.research.execution.operation.providers import SQLiteOperationStore
from noetrium_platform.research.execution.operation.runtime import OperationOwner
from noetrium_platform.foundation.kernel.kernel.operation import EffectCertainty, EffectClass, EffectReceipt
from noetrium_platform.infrastructure.reliability.effect.api import EffectReconciliationDisposition, EffectReconciliationProof


def _command_id(value: str = "cmd-1") -> CommandId:
    return CommandId(value)



def test_operation_reopens_and_replays_same_identity_after_restart(tmp_path: Path):
    path = tmp_path / "operations.sqlite3"
    first = OperationOwner(SQLiteOperationStore(path))
    created, is_new = first.submit(
        _command_id(),
        operation_id=OperationId("op-first"),
        now_unix=10.0,
    )
    assert is_new and created.state is OperationState.CREATED
    queued = first.queue(created, now_unix=11.0)

    second = OperationOwner(SQLiteOperationStore(path))
    replayed, is_new = second.submit(
        _command_id(),
        operation_id=OperationId("op-first"),
        now_unix=99.0,
    )
    assert not is_new
    assert replayed.operation_id == queued.operation_id
    assert replayed.state is OperationState.QUEUED

def test_same_command_can_own_multiple_distinct_operations(tmp_path: Path):
    owner = OperationOwner(SQLiteOperationStore(tmp_path / "operations.sqlite3"))
    first, _ = owner.submit(_command_id(), operation_id=OperationId("op-1"), now_unix=10.0)
    second, _ = owner.submit(_command_id(), operation_id=OperationId("op-2"), now_unix=10.0)
    assert first.command_id == second.command_id
    assert first.operation_id != second.operation_id


def test_operation_identity_contract_drift_fails_closed(tmp_path: Path):
    owner = OperationOwner(SQLiteOperationStore(tmp_path / "operations.sqlite3"))
    owner.submit(_command_id("cmd-1"), operation_id=OperationId("op-1"), now_unix=10.0)
    try:
        owner.submit(_command_id("cmd-2"), operation_id=OperationId("op-1"), now_unix=10.0)
    except OperationConflict:
        pass
    else:
        raise AssertionError("operation identity reuse with different command must fail closed")



def _effectful_owner(tmp_path: Path, suffix: str):
    owner = OperationOwner(SQLiteOperationStore(tmp_path / f"{suffix}.sqlite3"))
    created, _ = owner.submit(
        _command_id(f"cmd-{suffix}"),
        operation_id=OperationId(f"op-{suffix}"),
        effect_profile=OperationEffectProfile.RECONCILABLE,
        effect_id=EffectId(f"effect-{suffix}"),
        effect_request_id=f"request-{suffix}",
        effect_request_digest="d" * 64,
        now_unix=10.0,
    )
    admitted = owner.admit(created, now_unix=11.0)
    running = owner.begin_execution(admitted)
    return owner, running


def _proof(operation: OperationSnapshot, disposition, certainty):
    effect = None if certainty is None else EffectReceipt(
        operation.effect_id.value,
        operation.effect_request_digest,
        EffectClass.RECONCILABLE,
        certainty,
    )
    return EffectReconciliationProof(
        operation.effect_request_id,
        disposition,
        effect,
    )


def test_uncertain_effect_cannot_blindly_enter_recovery(tmp_path: Path):
    owner, running = _effectful_owner(tmp_path, "uncertain")
    unknown = owner.mark_effect_unknown(running)
    assert not hasattr(owner, "begin_recovery")
    assert not hasattr(owner, "transition")
    try:
        owner.begin_execution(unknown)
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "uncertain external effect must reconcile before execution resumes"
        )


def test_reconciliation_not_executed_allows_safe_retry(tmp_path: Path):
    owner, running = _effectful_owner(tmp_path, "retry")
    unknown = owner.mark_effect_unknown(running)
    recovered = owner.reconcile_effect(
        unknown,
        _proof(
            unknown,
            EffectReconciliationDisposition.NOT_APPLIED,
            EffectCertainty.NO_EFFECT,
        ),
    )
    assert recovered.state is OperationState.RECOVERING
    assert recovered.effect_certainty is OperationEffectCertainty.NOT_EXECUTED
    assert owner.begin_execution(recovered).state is OperationState.RUNNING


def test_reconciliation_executed_blocks_reexecution_and_can_complete(tmp_path: Path):
    owner, running = _effectful_owner(tmp_path, "executed")
    unknown = owner.mark_effect_unknown(running)
    recovered = owner.reconcile_effect(
        unknown,
        _proof(
            unknown,
            EffectReconciliationDisposition.APPLIED,
            EffectCertainty.EFFECT_CONFIRMED,
        ),
    )
    assert recovered.state is OperationState.RECOVERING
    try:
        owner.begin_execution(recovered)
    except RuntimeError:
        pass
    else:
        raise AssertionError("confirmed external effect must not be re-executed")
    completed = owner.complete(recovered, result_digest="d" * 64)
    assert completed.state is OperationState.COMPLETED
    assert completed.effect_certainty is OperationEffectCertainty.EXECUTED

def test_operation_store_rejects_partial_failure_corruption(tmp_path: Path):
    path = tmp_path / "operations-corrupt.sqlite3"
    owner = OperationOwner(SQLiteOperationStore(path))
    operation, _ = owner.submit(_command_id(), operation_id=OperationId("op-corrupt"), now_unix=10.0)
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE operations SET failure_code=? WHERE operation_id=?",
            ("ORPHAN_FAILURE_CODE", operation.operation_id.value),
        )
    try:
        SQLiteOperationStore(path).load(operation.operation_id)
    except OperationCorruption:
        pass
    else:
        raise AssertionError("partial operation failure columns must fail closed")



def test_cancelled_uncertain_effect_reconciles_not_executed_to_cancelled(tmp_path: Path):
    owner, running = _effectful_owner(tmp_path, "cancel-not-executed")
    cancelling = owner.request_cancel(running, "user cancelled")
    assert cancelling.state is OperationState.CANCELLING
    unknown = owner.recover_interrupted(cancelling)
    assert unknown.state is OperationState.UNKNOWN_EFFECT
    assert unknown.cancellation_requested
    assert unknown.cancellation_reason == "user cancelled"

    restarted = OperationOwner(
        SQLiteOperationStore(tmp_path / "cancel-not-executed.sqlite3")
    )
    persisted = restarted.require(unknown.operation_id)
    assert persisted.cancellation_requested
    cancelled = restarted.reconcile_effect(
        persisted,
        _proof(
            persisted,
            EffectReconciliationDisposition.NOT_APPLIED,
            EffectCertainty.NO_EFFECT,
        ),
    )
    assert cancelled.state is OperationState.CANCELLED
    assert cancelled.cancellation_reason == "user cancelled"


def test_cancelled_uncertain_effect_confirmed_executed_never_reexecutes(tmp_path: Path):
    owner, running = _effectful_owner(tmp_path, "cancel-executed")
    cancelling = owner.request_cancel(running, "user cancelled")
    unknown = owner.recover_interrupted(cancelling)
    recovered = owner.reconcile_effect(
        unknown,
        _proof(
            unknown,
            EffectReconciliationDisposition.APPLIED,
            EffectCertainty.EFFECT_CONFIRMED,
        ),
    )
    assert recovered.state is OperationState.RECOVERING
    assert recovered.cancellation_requested
    try:
        owner.begin_execution(recovered)
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "cancelled operation with confirmed effect must never re-execute"
        )
    completed = owner.complete(recovered, result_digest="e" * 64)
    assert completed.state is OperationState.COMPLETED
    assert completed.cancellation_requested
    assert completed.cancellation_reason == "user cancelled"


def test_effect_free_failure_after_cancel_request_preserves_cancellation_evidence(
    tmp_path: Path,
):
    owner = OperationOwner(SQLiteOperationStore(tmp_path / "cancel-fail.sqlite3"))
    created, _ = owner.submit(
        _command_id("cmd-cancel-fail"),
        operation_id=OperationId("op-cancel-fail"),
        now_unix=10.0,
    )
    admitted = owner.admit(created, now_unix=11.0)
    running = owner.begin_execution(admitted)
    cancelling = owner.request_cancel(running, "operator stop")
    failure = OperationFailure(
        OperationFailureKind.OPERATION_FAILURE,
        "STOP_FAILED",
        "operation failed while cancellation was in progress",
    )
    failed = owner.fail(cancelling, failure)
    assert failed.state is OperationState.FAILED
    assert failed.cancellation_requested
    assert failed.cancellation_reason == "operator stop"

def test_old_operation_schema_is_rejected_instead_of_silently_upgraded(tmp_path: Path):
    path = tmp_path / "old-operation-schema.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE operations (
            operation_id TEXT PRIMARY KEY, command_id TEXT NOT NULL, state TEXT NOT NULL,
            version INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
            parent_operation_id TEXT, effect_id TEXT, effect_profile TEXT NOT NULL,
            effect_certainty TEXT NOT NULL, result_digest TEXT, failure_kind TEXT,
            failure_code TEXT, failure_message TEXT, failure_retryable INTEGER,
            failure_reconciliation_required INTEGER, cancellation_reason TEXT)""")
    try:
        SQLiteOperationStore(path)
    except OperationCorruption:
        pass
    else:
        raise AssertionError("obsolete durable schema must require an explicit migration")



def test_operation_owner_cancellation_reason_does_not_coerce_non_text(tmp_path: Path):
    owner = OperationOwner(SQLiteOperationStore(tmp_path / "strict-cancel.sqlite3"))
    operation, _ = owner.submit(
        _command_id("cmd-strict-cancel"),
        operation_id=OperationId("op-strict-cancel"),
        now_unix=10.0,
    )
    try:
        owner.request_cancel(operation, 123)  # type: ignore[arg-type]
    except TypeError:
        pass
    else:
        raise AssertionError("operation cancellation reason must remain typed")

def test_operation_store_cas_rejects_version_skip(tmp_path: Path):
    store = SQLiteOperationStore(tmp_path / "cas-version.sqlite3")
    owner = OperationOwner(store)
    current, _ = owner.submit(
        _command_id("cmd-cas-version"), operation_id=OperationId("op-cas-version"), now_unix=10.0
    )
    skipped = OperationSnapshot(
        current.operation_id, current.command_id, OperationState.QUEUED, 2,
        current.created_at_unix, 11.0,
    )
    try:
        store.compare_and_swap(current, skipped)
    except OperationConflict:
        pass
    else:
        raise AssertionError("operation CAS must advance exactly one durable version")


def test_operation_store_cas_rejects_immutable_identity_mutation(tmp_path: Path):
    store = SQLiteOperationStore(tmp_path / "cas-identity.sqlite3")
    owner = OperationOwner(store)
    current, _ = owner.submit(
        _command_id("cmd-cas-identity"), operation_id=OperationId("op-cas-identity"), now_unix=10.0
    )
    mutated = OperationSnapshot(
        current.operation_id, current.command_id, OperationState.QUEUED, 1,
        current.created_at_unix, 11.0, parent_operation_id=OperationId("op-parent"),
    )
    try:
        store.compare_and_swap(current, mutated)
    except OperationConflict:
        pass
    else:
        raise AssertionError("operation CAS must not rewrite immutable parent/effect identity")


def test_operation_store_cas_rejects_illegal_state_jump(tmp_path: Path):
    store = SQLiteOperationStore(tmp_path / "cas-state.sqlite3")
    owner = OperationOwner(store)
    current, _ = owner.submit(
        _command_id("cmd-cas-state"), operation_id=OperationId("op-cas-state"), now_unix=10.0
    )
    jumped = OperationSnapshot(
        current.operation_id, current.command_id, OperationState.COMPLETED, 1,
        current.created_at_unix, 11.0,
    )
    try:
        store.compare_and_swap(current, jumped)
    except OperationConflict:
        pass
    else:
        raise AssertionError("operation store must enforce lifecycle transitions even for direct CAS")



def test_operation_owner_effectful_inflight_failure_requires_reconciliation(
    tmp_path: Path,
):
    failure = OperationFailure(
        OperationFailureKind.OPERATION_FAILURE,
        "FAILED",
        "handler failed",
    )
    running_owner, running = _effectful_owner(
        tmp_path,
        "effectful-fail-running",
    )
    try:
        running_owner.fail(running, failure)
    except IllegalOperationTransition as exc:
        assert "UNKNOWN_EFFECT" in str(exc)
    else:
        raise AssertionError(
            "effectful RUNNING failure must not become terminal FAILED"
        )
    assert (
        running_owner.require(running.operation_id).state
        is OperationState.RUNNING
    )

    cancelling_owner, running = _effectful_owner(
        tmp_path,
        "effectful-fail-cancelling",
    )
    cancelling = cancelling_owner.request_cancel(running, "stop")
    try:
        cancelling_owner.fail(cancelling, failure)
    except IllegalOperationTransition as exc:
        assert "UNKNOWN_EFFECT" in str(exc)
    else:
        raise AssertionError(
            "effectful CANCELLING failure must not become terminal FAILED"
        )
    assert (
        cancelling_owner.require(cancelling.operation_id).state
        is OperationState.CANCELLING
    )


def test_operation_owner_effect_free_running_failure_remains_legal(tmp_path: Path):
    owner = OperationOwner(
        SQLiteOperationStore(tmp_path / "effect-free-fail.sqlite3")
    )
    created, _ = owner.submit(
        _command_id("cmd-effect-free-fail"),
        operation_id=OperationId("op-effect-free-fail"),
        now_unix=10.0,
    )
    admitted = owner.admit(created, now_unix=11.0)
    running = owner.begin_execution(admitted)
    failure = OperationFailure(
        OperationFailureKind.OPERATION_FAILURE,
        "FAILED",
        "handler failed",
    )
    failed = owner.fail(running, failure)
    assert failed.state is OperationState.FAILED
