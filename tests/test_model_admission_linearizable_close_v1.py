"""Controller closure must serialize with every post-Authority claim handoff."""
from __future__ import annotations

from threading import Event, Thread, current_thread

import pytest

from model_admission_test_support import make_model_admission_controller
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionClosed


class _PausedAuthoritySnapshot:
    def __init__(self, delegate, observed: Event, resume: Event) -> None:
        self._delegate = delegate
        self._observed = observed
        self._resume = resume

    def snapshot_for_resource_keys(self, keys):
        result = self._delegate.snapshot_for_resource_keys(keys)
        if current_thread().name == "closing" and not self._observed.is_set():
            self._observed.set()
            if not self._resume.wait(5):
                raise AssertionError("close snapshot barrier timed out")
        return result

    def __getattr__(self, key):
        return getattr(self._delegate, key)


@pytest.mark.parametrize("reserve_continuity", (False, True))
def test_close_snapshot_cannot_race_with_claim_handoff(reserve_continuity: bool) -> None:
    controller = make_model_admission_controller(1)
    if reserve_continuity:
        controller.qualify_continuity(1)
    observed, resume = Event(), Event()
    controller._authority = _PausedAuthoritySnapshot(
        controller._authority, observed, resume
    )
    close_failures: list[BaseException] = []
    attempt_errors: list[BaseException] = []
    obtained: list[object] = []

    def closer() -> None:
        try:
            controller.close()
        except BaseException as exc:
            close_failures.append(exc)

    def contender() -> None:
        try:
            lease = (
                controller.try_reserve_continuity(owner_id="worker", flow_id="flow")
                if reserve_continuity
                else controller.acquire(timeout_seconds=2, owner_id="worker")
            )
            if lease is not None:
                obtained.append(lease)
        except BaseException as exc:
            attempt_errors.append(exc)

    closing = Thread(target=closer, name="closing", daemon=True)
    requesting = Thread(target=contender, name="requesting", daemon=True)
    closing.start()
    assert observed.wait(3), "close never observed Authority's empty cut"
    requesting.start()
    # Give the contender an opportunity to reach the grant-handoff window.
    requesting.join(timeout=0.1)
    resume.set()
    closing.join(timeout=3)
    requesting.join(timeout=3)
    assert not closing.is_alive()
    assert not requesting.is_alive()
    assert close_failures == []
    assert controller.closed
    assert obtained == []
    assert len(attempt_errors) == 1
    assert isinstance(attempt_errors[0], ModelAdmissionClosed)
    assert controller.snapshot().active == 0
    controller._test_registry.close()
