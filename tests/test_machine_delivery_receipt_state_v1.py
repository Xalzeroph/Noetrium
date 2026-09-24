from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    DeliveryReceipt,
    DeliveryStatus,
    DirectoryMachineOutbox,
    InMemoryMachineOutbox,
    MachineCommand,
    MachineCommit,
    MachineConflict,
    canonical_digest,
)


def _commit() -> MachineCommit:
    emitted = MachineCommand(
        command_id="child-command",
        machine_id="child-machine",
        expected_revision=0,
        kind="step",
        payload={"value": 1},
        scope=("run:child-machine",),
    )
    return MachineCommit(
        machine_id="parent-machine",
        command_id="parent-command",
        base_revision=0,
        revision=1,
        proposal_digest=canonical_digest({"proposal": 1}),
        command_digest=canonical_digest({"command": 1}),
        program_digest=canonical_digest({"program": 1}),
        program_lock_digest=canonical_digest({"lock": 1}),
        state={"done": True},
        emitted_commands=(emitted,),
    )


def _receipt(envelope, status: str, attempt: int, detail: str | None = None):
    return DeliveryReceipt(
        envelope_id=envelope.envelope_id,
        envelope_digest=envelope.envelope_digest,
        status=status,
        attempt=attempt,
        detail=detail,
    )


@pytest.mark.parametrize(
    "factory",
    (
        lambda root: InMemoryMachineOutbox(),
        lambda root: DirectoryMachineOutbox(root),
    ),
)
def test_delivered_receipt_is_irreversible(
    tmp_path: Path,
    factory,
) -> None:
    outbox = factory(tmp_path / "delivery")
    envelope = outbox.enqueue(_commit())[0]
    delivered = _receipt(envelope, DeliveryStatus.DELIVERED, 1)
    assert outbox.mark(delivered) == delivered
    assert outbox.pending() == ()

    for status in (
        DeliveryStatus.PENDING,
        DeliveryStatus.UNKNOWN,
        DeliveryStatus.FAILED,
    ):
        with pytest.raises(MachineConflict, match="terminal"):
            outbox.mark(_receipt(envelope, status, 2))
        assert outbox.pending() == ()

    # Exact retry remains idempotent.
    assert outbox.mark(delivered) == delivered


def test_directory_delivered_terminality_survives_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "delivery"
    first = DirectoryMachineOutbox(root)
    envelope = first.enqueue(_commit())[0]
    delivered = _receipt(envelope, DeliveryStatus.DELIVERED, 3)
    assert first.mark(delivered) == delivered

    reopened = DirectoryMachineOutbox(root)
    assert reopened.pending() == ()
    with pytest.raises(MachineConflict, match="terminal"):
        reopened.mark(
            _receipt(
                envelope,
                DeliveryStatus.UNKNOWN,
                99,
                "stale future acknowledgement",
            )
        )
    assert DirectoryMachineOutbox(root).pending() == ()


@pytest.mark.parametrize(
    "factory",
    (
        lambda root: InMemoryMachineOutbox(),
        lambda root: DirectoryMachineOutbox(root),
    ),
)
def test_unknown_receipt_can_resolve_without_fabricating_new_attempt(
    tmp_path: Path,
    factory,
) -> None:
    outbox = factory(tmp_path / "delivery")
    envelope = outbox.enqueue(_commit())[0]
    unknown = _receipt(
        envelope,
        DeliveryStatus.UNKNOWN,
        1,
        "acknowledgement lost",
    )
    assert outbox.mark(unknown) == unknown
    assert outbox.pending() == (envelope,)

    delivered = _receipt(
        envelope,
        DeliveryStatus.DELIVERED,
        1,
        "reconciled by receiver evidence",
    )
    assert outbox.mark(delivered) == delivered
    assert outbox.pending() == ()


@pytest.mark.parametrize(
    "factory",
    (
        lambda root: InMemoryMachineOutbox(),
        lambda root: DirectoryMachineOutbox(root),
    ),
)
def test_same_attempt_non_unknown_receipt_drift_fails_closed(
    tmp_path: Path,
    factory,
) -> None:
    outbox = factory(tmp_path / "delivery")
    envelope = outbox.enqueue(_commit())[0]
    failed = _receipt(envelope, DeliveryStatus.FAILED, 1, "known failure")
    assert outbox.mark(failed) == failed
    with pytest.raises(MachineConflict, match="same attempt"):
        outbox.mark(
            _receipt(
                envelope,
                DeliveryStatus.DELIVERED,
                1,
                "contradictory late success",
            )
        )
