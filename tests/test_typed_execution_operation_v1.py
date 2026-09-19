from noetrium_platform.research.execution.command.api import ExecutionCommand
from noetrium_platform.research.execution.operation.api import (
    EffectId, IllegalOperationTransition, OperationEffectCertainty, OperationEffectProfile, OperationFailure,
    OperationFailureKind, OperationId, OperationSnapshot, OperationState, revise_operation, transition_operation,
)

DIGEST = "a" * 64


def test_command_identity_is_distinct_from_operation_identity():
    command = ExecutionCommand.create(command_id="cmd-1", command_type="process.launch",
                                      payload_schema="launch.v1", payload_digest=DIGEST,
                                      deduplication_key="submit:1", now_unix=10.0)
    operation = OperationSnapshot(OperationId("op-1"), command.command_id, OperationState.CREATED, 0, 10.0, 10.0)
    assert command.command_id.value == "cmd-1"
    assert operation.operation_id.value == "op-1"


def test_terminal_operation_cannot_restart():
    current = OperationSnapshot(OperationId("op"), ExecutionCommand.create(
        command_id="cmd", command_type="x", payload_schema="x.v1", payload_digest=DIGEST,
        now_unix=1.0).command_id, OperationState.COMPLETED, 2, 1.0, 2.0)
    try:
        transition_operation(current, OperationState.RUNNING, now_unix=3.0)
    except IllegalOperationTransition:
        pass
    else:
        raise AssertionError("COMPLETED -> RUNNING must be rejected")


def test_unknown_effect_is_explicit_and_requires_reconciliation():
    command = ExecutionCommand.create(command_id="cmd", command_type="external.write",
                                      payload_schema="x.v1", payload_digest=DIGEST, now_unix=1.0)
    running = OperationSnapshot(OperationId("op"), command.command_id, OperationState.RUNNING, 3, 1.0, 2.0,
                                effect_id=EffectId("effect-1"), effect_profile=OperationEffectProfile.RECONCILABLE, effect_request_id="request-proof", effect_request_digest=DIGEST)
    failure = OperationFailure(OperationFailureKind.EXTERNAL_EFFECT_UNCERTAIN, "EFFECT_ACK_LOST",
                               "effect acknowledgement lost", retryable=False, reconciliation_required=True)
    unknown = transition_operation(running, OperationState.UNKNOWN_EFFECT, now_unix=3.0,
                                   effect_certainty=OperationEffectCertainty.UNKNOWN, failure=failure)
    assert unknown.state is OperationState.UNKNOWN_EFFECT
    assert unknown.effect_certainty is OperationEffectCertainty.UNKNOWN
    try:
        transition_operation(unknown, OperationState.RECOVERING, now_unix=4.0)
    except ValueError:
        pass
    else:
        raise AssertionError("UNKNOWN_EFFECT cannot leave reconciliation with unresolved certainty")


def test_operation_snapshot_rejects_contradictory_terminal_evidence():
    command = ExecutionCommand.create(command_id="cmd-x", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    try:
        OperationSnapshot(OperationId("op-x"), command.command_id, OperationState.RUNNING, 1, 1.0, 2.0,
                          result_digest="f" * 64)
    except ValueError:
        pass
    else:
        raise AssertionError("non-terminal operation cannot carry final result digest")


def test_uncertain_effect_failure_cannot_be_terminal_failed():
    command = ExecutionCommand.create(command_id="cmd-y", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    failure = OperationFailure(OperationFailureKind.EXTERNAL_EFFECT_UNCERTAIN, "ACK_LOST", "ack lost",
                               reconciliation_required=True)
    try:
        OperationSnapshot(OperationId("op-y"), command.command_id, OperationState.FAILED, 2, 1.0, 2.0,
                          effect_id=EffectId("effect-y"), effect_profile=OperationEffectProfile.RECONCILABLE, effect_request_id="request-proof", effect_request_digest=DIGEST,
                          failure=failure)
    except ValueError:
        pass
    else:
        raise AssertionError("uncertain effect cannot be collapsed into FAILED")


def test_operation_transition_rejects_backward_durable_timestamp():
    command = ExecutionCommand.create(command_id="cmd-z", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    current = OperationSnapshot(OperationId("op-z"), command.command_id, OperationState.CREATED, 0, 1.0, 5.0)
    try:
        transition_operation(current, OperationState.QUEUED, now_unix=4.0)
    except ValueError:
        pass
    else:
        raise AssertionError("durable operation timestamps must not move backwards")


def test_operation_cannot_be_its_own_parent():
    command = ExecutionCommand.create(command_id="cmd-p", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    operation_id = OperationId("op-p")
    try:
        OperationSnapshot(operation_id, command.command_id, OperationState.CREATED, 0, 1.0, 1.0,
                          parent_operation_id=operation_id)
    except ValueError:
        pass
    else:
        raise AssertionError("operation parent identity cannot self-reference")


def test_operation_and_effect_identity_do_not_coerce_non_text_values():
    for factory in (OperationId, EffectId):
        try:
            factory(123)  # type: ignore[arg-type]
        except TypeError:
            pass
        else:
            raise AssertionError("operation/effect identity must remain typed")


def test_operation_failure_fields_are_strictly_typed():
    for factory in (
        lambda: OperationFailure("runtime_failure", "E", "bad"),  # type: ignore[arg-type]
        lambda: OperationFailure(OperationFailureKind.RUNTIME_FAILURE, "E", "bad", retryable=1),  # type: ignore[arg-type]
    ):
        try:
            factory()
        except TypeError:
            pass
        else:
            raise AssertionError("operation failure fields must reject implicit coercion")


def test_operation_snapshot_authority_fields_reject_wrong_types():
    command = ExecutionCommand.create(command_id="cmd-strict", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    cases = (
        lambda: OperationSnapshot(OperationId("op-a"), command.command_id, "created", 0, 1.0, 1.0),  # type: ignore[arg-type]
        lambda: OperationSnapshot(OperationId("op-b"), command.command_id, OperationState.CREATED, True, 1.0, 1.0),
        lambda: OperationSnapshot(OperationId("op-c"), command.command_id, OperationState.CREATED, 0, True, 1.0),
        lambda: OperationSnapshot(OperationId("op-d"), command.command_id, OperationState.CREATED, 0, 1.0, 1.0,
                                  parent_operation_id="parent"),  # type: ignore[arg-type]
        lambda: OperationSnapshot(OperationId("op-e"), command.command_id, OperationState.CREATED, 0, 1.0, 1.0,
                                  effect_profile="none"),  # type: ignore[arg-type]
    )
    for factory in cases:
        try:
            factory()
        except TypeError:
            pass
        else:
            raise AssertionError("operation authority fields must reject wrong types")


def test_transition_cannot_mutate_operation_authority_identity():
    command = ExecutionCommand.create(command_id="cmd-transition", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    current = OperationSnapshot(OperationId("op-transition"), command.command_id, OperationState.CREATED, 0, 1.0, 1.0)
    try:
        transition_operation(current, OperationState.QUEUED, operation_id=OperationId("other"))
    except TypeError:
        pass
    else:
        raise AssertionError("state transition must not rewrite operation identity")


def test_revision_is_only_for_cancellation_evidence_in_recovery_states():
    command = ExecutionCommand.create(command_id="cmd-revise", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    created = OperationSnapshot(OperationId("op-revise"), command.command_id, OperationState.CREATED, 0, 1.0, 1.0)
    try:
        revise_operation(created, cancellation_requested=True, cancellation_reason="stop")
    except IllegalOperationTransition:
        pass
    else:
        raise AssertionError("metadata revision must not bypass CREATED cancellation transition")


def test_transition_cannot_rebind_effect_identity():
    command = ExecutionCommand.create(command_id="cmd-effect-id", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    current = OperationSnapshot(OperationId("op-effect-id"), command.command_id, OperationState.ADMITTED, 1, 1.0, 1.0,
                                effect_id=EffectId("effect-stable"), effect_profile=OperationEffectProfile.RECONCILABLE, effect_request_id="request-proof", effect_request_digest=DIGEST)
    try:
        transition_operation(current, OperationState.RUNNING, effect_id=EffectId("effect-other"))
    except TypeError:
        pass
    else:
        raise AssertionError("operation transition must not rebind stable effect identity")


def test_pre_cancellation_states_cannot_carry_cancellation_intent():
    command = ExecutionCommand.create(command_id="cmd-cancel-state", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    for state in (OperationState.CREATED, OperationState.QUEUED, OperationState.ADMITTED, OperationState.RUNNING):
        try:
            OperationSnapshot(OperationId(f"op-{state.value}"), command.command_id, state, 1, 1.0, 2.0,
                              cancellation_requested=True, cancellation_reason="stop")
        except ValueError:
            pass
        else:
            raise AssertionError(f"{state.value} must not carry durable cancellation intent")


def test_transition_cannot_erase_or_rewrite_cancellation_evidence():
    command = ExecutionCommand.create(command_id="cmd-cancel-monotonic", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    current = OperationSnapshot(OperationId("op-cancel-monotonic"), command.command_id,
                                OperationState.CANCELLING, 3, 1.0, 2.0,
                                cancellation_requested=True, cancellation_reason="first")
    for changes in (
        {"cancellation_requested": False, "cancellation_reason": None},
        {"cancellation_reason": "second"},
    ):
        try:
            transition_operation(current, OperationState.COMPLETED, now_unix=3.0, **changes)
        except ValueError:
            pass
        else:
            raise AssertionError("cancellation evidence must be monotonic and first-request-wins")


def test_executed_effect_certainty_cannot_regress():
    command = ExecutionCommand.create(command_id="cmd-effect-monotonic", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    current = OperationSnapshot(OperationId("op-effect-monotonic"), command.command_id,
                                OperationState.RECOVERING, 4, 1.0, 2.0,
                                effect_id=EffectId("effect-monotonic"),
                                effect_profile=OperationEffectProfile.RECONCILABLE, effect_request_id="request-proof", effect_request_digest=DIGEST,
                                effect_certainty=OperationEffectCertainty.EXECUTED)
    try:
        transition_operation(current, OperationState.COMPLETED, now_unix=3.0,
                             effect_certainty=OperationEffectCertainty.NOT_EXECUTED)
    except ValueError:
        pass
    else:
        raise AssertionError("executed external effect truth must never regress")


def test_not_executed_effect_can_resolve_to_executed():
    command = ExecutionCommand.create(command_id="cmd-effect-forward", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    current = OperationSnapshot(OperationId("op-effect-forward"), command.command_id,
                                OperationState.RUNNING, 2, 1.0, 2.0,
                                effect_id=EffectId("effect-forward"),
                                effect_profile=OperationEffectProfile.RECONCILABLE, effect_request_id="request-proof", effect_request_digest=DIGEST)
    completed = transition_operation(current, OperationState.COMPLETED, now_unix=3.0,
                                     effect_certainty=OperationEffectCertainty.EXECUTED)
    assert completed.effect_certainty is OperationEffectCertainty.EXECUTED


def test_recovery_cancellation_revision_is_idempotent_and_reason_is_immutable():
    command = ExecutionCommand.create(command_id="cmd-revise-first", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    current = OperationSnapshot(OperationId("op-revise-first"), command.command_id,
                                OperationState.RECOVERING, 5, 1.0, 2.0,
                                effect_id=EffectId("effect-revise-first"),
                                effect_profile=OperationEffectProfile.RECONCILABLE, effect_request_id="request-proof", effect_request_digest=DIGEST,
                                effect_certainty=OperationEffectCertainty.EXECUTED,
                                cancellation_requested=True, cancellation_reason="first")
    replay = revise_operation(current, cancellation_requested=True, cancellation_reason="first")
    assert replay is current
    try:
        revise_operation(current, cancellation_requested=True, cancellation_reason="second")
    except ValueError:
        pass
    else:
        raise AssertionError("first durable cancellation reason must be immutable")


def test_pre_execution_cancel_cannot_enter_cancelling_state():
    command = ExecutionCommand.create(command_id="cmd-cancel-direct", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    for state in (OperationState.QUEUED, OperationState.ADMITTED):
        current = OperationSnapshot(OperationId(f"op-{state.value}"), command.command_id, state, 1, 1.0, 2.0)
        try:
            transition_operation(
                current, OperationState.CANCELLING, now_unix=3.0,
                cancellation_requested=True, cancellation_reason="stop",
            )
        except IllegalOperationTransition:
            pass
        else:
            raise AssertionError("pre-execution cancellation must become terminal CANCELLED")


def test_recovering_not_executed_cannot_record_nonterminal_cancel_revision():
    command = ExecutionCommand.create(command_id="cmd-recover-cancel", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    current = OperationSnapshot(OperationId("op-recover-cancel"), command.command_id,
                                OperationState.RECOVERING, 3, 1.0, 2.0)
    try:
        revise_operation(current, cancellation_requested=True, cancellation_reason="stop")
    except IllegalOperationTransition:
        pass
    else:
        raise AssertionError("NOT_EXECUTED recovery cancellation must transition to CANCELLED")


def test_effectful_inflight_failure_requires_unknown_effect_reconciliation():
    command = ExecutionCommand.create(command_id="cmd-effect-fail", command_type="x", payload_schema="x.v1",
                                      payload_digest=DIGEST, now_unix=1.0)
    current = OperationSnapshot(OperationId("op-effect-fail"), command.command_id,
                                OperationState.RUNNING, 2, 1.0, 2.0,
                                effect_id=EffectId("effect-fail"),
                                effect_profile=OperationEffectProfile.RECONCILABLE, effect_request_id="request-proof", effect_request_digest=DIGEST)
    failure = OperationFailure(OperationFailureKind.OPERATION_FAILURE, "FAILED", "handler failed")
    try:
        transition_operation(current, OperationState.FAILED, now_unix=3.0, failure=failure)
    except IllegalOperationTransition:
        pass
    else:
        raise AssertionError("effectful in-flight failure must reconcile UNKNOWN_EFFECT before terminal failure")
