from __future__ import annotations

from model_admission_test_support import make_model_admission_controller

from threading import Event, Thread
import time

from noetrium_platform.foundation.kernel.kernel.complexity import ComplexityBound
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionController


def _wait_for_waiters(controller: ModelAdmissionController, count: int) -> None:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if controller.snapshot().waiting >= count:
            return
        time.sleep(0.002)
    raise AssertionError(f"expected at least {count} model admission waiters")


def test_capacity_fence_preserves_capacity_and_progress() -> None:
    controller = make_model_admission_controller(1)
    running = controller.acquire(timeout_seconds=0.1, owner_id="study-running")
    acquired: list[str] = []

    def wait(name: str, owner: str) -> None:
        lease = controller.acquire(timeout_seconds=1.0, owner_id=owner)
        acquired.append(name)
        lease.release()

    first = Thread(target=wait, args=("first", "study-a"))
    second = Thread(target=wait, args=("second", "study-b"))
    first.start()
    _wait_for_waiters(controller, 1)
    second.start()
    _wait_for_waiters(controller, 2)
    running.release()
    first.join(1)
    second.join(1)
    assert sorted(acquired) == ["first", "second"]


def test_single_owner_can_fill_entire_qualified_capacity() -> None:
    controller = make_model_admission_controller(3)
    leases = [
        controller.acquire(timeout_seconds=0.1, owner_id="study-a")
        for _ in range(3)
    ]
    snapshot = controller.snapshot()
    assert snapshot.active == 3
    assert snapshot.waiting == 0
    assert snapshot.owners[0].owner_id == "study-a"
    assert snapshot.owners[0].active == 3
    for lease in reversed(leases):
        lease.release()


def test_owner_snapshot_is_observability_only() -> None:
    controller = make_model_admission_controller(1)
    lease = controller.acquire(timeout_seconds=0.1, owner_id="study-a")
    done = Event()

    def waiter() -> None:
        queued = controller.acquire(timeout_seconds=1.0, owner_id="study-b")
        queued.release()
        done.set()

    thread = Thread(target=waiter)
    thread.start()
    _wait_for_waiters(controller, 1)
    rows = {row.owner_id: row for row in controller.snapshot().owners}
    assert rows["study-a"].active == 1 and rows["study-a"].waiting == 0
    assert rows["study-b"].active == 0 and rows["study-b"].waiting == 1
    lease.release()
    assert done.wait(1)
    thread.join(1)


def test_capacity_selection_is_constant_space_authority_claim() -> None:
    from noetrium_platform.capabilities.model.serving.runtime.admission import (
        MODEL_ADMISSION_CAPACITY_SELECTION_COMPLEXITY,
    )

    contract = MODEL_ADMISSION_CAPACITY_SELECTION_COMPLEXITY
    assert contract.time_upper_bound == ComplexityBound.constant()
    assert contract.space_upper_bound == ComplexityBound.constant()
