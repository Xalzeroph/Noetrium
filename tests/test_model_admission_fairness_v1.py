from __future__ import annotations

from threading import Event, Thread
import time

from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionController


def _wait_for_waiters(controller: ModelAdmissionController, count: int) -> None:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if controller.snapshot().waiting >= count:
            return
        time.sleep(0.002)
    raise AssertionError(f"expected at least {count} model admission waiters")


def test_competing_owner_cannot_be_starved_by_older_same_owner_backlog() -> None:
    controller = ModelAdmissionController(1)
    running = controller.acquire(timeout_seconds=0.1, owner_id="study-a")
    acquired: list[tuple[str, object]] = []
    release_a2 = Event()

    def wait_a2() -> None:
        lease = controller.acquire(timeout_seconds=1.0, owner_id="study-a")
        acquired.append(("a2", lease))
        release_a2.wait(1)
        lease.release()

    def wait_b1() -> None:
        lease = controller.acquire(timeout_seconds=1.0, owner_id="study-b")
        acquired.append(("b1", lease))
        lease.release()

    a2 = Thread(target=wait_a2)
    b1 = Thread(target=wait_b1)
    a2.start()
    _wait_for_waiters(controller, 1)
    b1.start()
    _wait_for_waiters(controller, 2)

    running.release()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not acquired:
        time.sleep(0.002)
    assert acquired and acquired[0][0] == "b1"
    release_a2.set()
    a2.join(1)
    b1.join(1)
    assert [name for name, _lease in acquired] == ["b1", "a2"]


def test_single_owner_can_fill_entire_qualified_capacity() -> None:
    controller = ModelAdmissionController(3)
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


def test_owner_snapshot_reports_active_and_waiting_without_changing_capacity() -> None:
    controller = ModelAdmissionController(1)
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
