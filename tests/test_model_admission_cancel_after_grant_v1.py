"""A cancellation concurrent with Resource Authority admission cannot leak a slot."""
from __future__ import annotations

from threading import Event

import pytest

from model_admission_test_support import make_model_admission_controller
from noetrium_platform.foundation.kernel.concurrency.api import TaskCancelled


class _Cancellation:
    def __init__(self) -> None:
        self._cancelled = Event()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def reason(self) -> str | None:
        return "cancelled during authority admission" if self.cancelled else None

    def cancel(self) -> None:
        self._cancelled.set()


class _CancelAfterGrant:
    """Delegates to the genuine Authority; injects cancellation after commit."""

    def __init__(self, authority, cancellation: _Cancellation) -> None:
        self._authority = authority
        self._cancellation = cancellation

    def admit_bundle(self, candidate_groups):
        granted = self._authority.admit_bundle(candidate_groups)
        self._cancellation.cancel()
        return granted

    def __getattr__(self, name):
        return getattr(self._authority, name)


def test_ordinary_admission_cancels_after_grant_without_leaking_claim() -> None:
    controller = make_model_admission_controller(1)
    cancellation = _Cancellation()
    controller._authority = _CancelAfterGrant(controller._authority, cancellation)
    with pytest.raises(TaskCancelled, match="cancelled during authority admission"):
        controller.acquire(owner_id="scientist", cancellation=cancellation)
    assert controller.snapshot().active == 0
    controller.close()


def test_continuity_borrow_cancels_after_grant_without_leaking_claim() -> None:
    controller = make_model_admission_controller(1)
    controller.qualify_continuity(1)
    continuity = controller.try_reserve_continuity(owner_id="scientist", flow_id="flow")
    assert continuity is not None
    cancellation = _Cancellation()
    controller._authority = _CancelAfterGrant(controller._authority, cancellation)
    with pytest.raises(TaskCancelled, match="cancelled during authority admission"):
        controller.acquire(
            owner_id="scientist",
            continuity_claim_id=continuity.claim_id,
            cancellation=cancellation,
        )
    assert controller.snapshot().active == 0
    continuity.release()
    controller.close()


def test_reentrant_close_inside_authority_grant_fails_without_deadlock() -> None:
    controller = make_model_admission_controller(1)
    authority = controller._authority

    class _ReentrantClose:
        def admit_bundle(self, candidate_groups):
            # Same-thread close cannot await its own unfinished transaction.
            with pytest.raises(RuntimeError, match="reentrantly"):
                controller.close()
            return authority.admit_bundle(candidate_groups)

        def __getattr__(self, name):
            return getattr(authority, name)

    controller._authority = _ReentrantClose()
    lease = controller.acquire(owner_id="scientist")
    lease.release()
    controller.close()
    assert controller.closed
    assert controller.snapshot().active == 0


def test_close_racing_with_authority_grant_waits_for_physical_rollback() -> None:
    from threading import Thread
    import time

    from noetrium_platform.capabilities.model.serving.api import ModelAdmissionClosed

    controller = make_model_admission_controller(1)
    authority = controller._authority
    started, resume = Event(), Event()
    errors: list[BaseException] = []
    close_errors: list[BaseException] = []

    class _PauseGrant:
        def admit_bundle(self, candidate_groups):
            started.set()
            assert resume.wait(4), "authorization never resumed"
            return authority.admit_bundle(candidate_groups)

        def __getattr__(self, name):
            return getattr(authority, name)

    controller._authority = _PauseGrant()

    def contender() -> None:
        try:
            controller.acquire(owner_id="scientist")
        except BaseException as exc:
            errors.append(exc)

    def closer() -> None:
        try:
            controller.close()
        except BaseException as exc:
            close_errors.append(exc)

    requesting = Thread(target=contender, daemon=True)
    closing = Thread(target=closer, daemon=True)
    requesting.start()
    try:
        assert started.wait(2)
        closing.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with controller._cv:
                if controller._closing:
                    break
            time.sleep(0.002)
        with controller._cv:
            assert controller._closing
        assert not controller.closed
        assert closing.is_alive()
    finally:
        resume.set()
        requesting.join(4)
        if closing.ident is not None:
            closing.join(4)
    assert not requesting.is_alive()
    assert not closing.is_alive()
    assert close_errors == []
    assert len(errors) == 1
    assert isinstance(errors[0], ModelAdmissionClosed)
    assert controller.closed
    assert controller.snapshot().active == 0
    assert controller.snapshot().waiting == 0
