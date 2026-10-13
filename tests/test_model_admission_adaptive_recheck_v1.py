"""Cross-process capacity contention avoids repeated 10ms SQLite writes."""
from __future__ import annotations

from threading import Event, Thread
import time

import pytest

from model_admission_test_support import make_model_admission_controller
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionTimeout


class _CountAuthority:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.attempts = 0

    def admit_bundle(self, groups):
        self.attempts += 1
        return self._delegate.admit_bundle(groups)

    def __getattr__(self, name):
        return getattr(self._delegate, name)


def test_prolonged_conflict_reduces_authority_probes_without_changing_deadline() -> None:
    controller = make_model_admission_controller(1)
    first = controller.acquire(owner_id="holder")
    counted = _CountAuthority(controller._authority)
    controller._authority = counted
    started = time.monotonic()
    try:
        with pytest.raises(ModelAdmissionTimeout):
            controller.acquire(timeout_seconds=0.28, owner_id="blocked")
        elapsed = time.monotonic() - started
        assert 0.24 <= elapsed < 0.85
        # Fixed 10ms polling would attempt about 28 transactions.
        assert 3 <= counted.attempts <= 10, counted.attempts
        assert controller.snapshot().waiting == 0
    finally:
        first.release()
        controller.close()
        controller._test_registry.close()


def test_commit_backed_admission_sleeps_without_periodic_sqlite_retries() -> None:
    """Event-backed waiting never spins on the Authority transaction."""
    from threading import Lock

    class CommitFeed:
        def __init__(self):
            self.callbacks = []
            self.lock = Lock()

        def subscribe(self, resource_keys, callback):
            assert resource_keys
            with self.lock:
                self.callbacks.append(callback)

            def unsubscribe():
                with self.lock:
                    self.callbacks.remove(callback)
            return unsubscribe

        def emit(self):
            with self.lock:
                callbacks = tuple(self.callbacks)
            for callback in callbacks:
                callback()

        def close(self):
            with self.lock:
                self.callbacks.clear()

    controller = make_model_admission_controller(1)
    holder = controller.acquire(owner_id="holder")
    feed = CommitFeed()
    controller._change_feed = feed
    controller._test_registry._change_feed = feed
    second_authorization = Event()
    third_authorization = Event()

    class CountingAuthority(_CountAuthority):
        def admit_bundle(self, groups):
            try:
                return super().admit_bundle(groups)
            finally:
                if self.attempts >= 2:
                    second_authorization.set()
                if self.attempts >= 3:
                    third_authorization.set()

    counted = CountingAuthority(controller._authority)
    controller._authority = counted
    finished = Event()
    errors = []

    def await_capacity():
        try:
            with controller.acquire(owner_id="waiter", timeout_seconds=3):
                finished.set()
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=await_capacity, daemon=True)
    thread.start()
    try:
        assert second_authorization.wait(2)
        attempts = counted.attempts
        time.sleep(0.12)
        assert counted.attempts == attempts, "event-backed waiter polled SQLite"
        feed.emit()
        assert third_authorization.wait(2)
        assert not finished.is_set()
        holder.release()
        assert finished.wait(2)
    finally:
        if not holder._released:
            holder.release()
        thread.join(timeout=4)
        if not thread.is_alive():
            controller.close()
            controller._test_registry.close()
    assert not thread.is_alive()
    assert errors == []


def test_local_release_wakes_even_after_backoff_has_grown() -> None:
    controller = make_model_admission_controller(1)
    first = controller.acquire(owner_id="holder")
    obtained = Event()
    errors: list[BaseException] = []

    def waiter() -> None:
        try:
            with controller.acquire(timeout_seconds=2, owner_id="blocked"):
                obtained.set()
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=waiter, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 1
        while controller.snapshot().waiting < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert controller.snapshot().waiting == 1
        time.sleep(0.23)
        released_at = time.monotonic()
        first.release()
        assert obtained.wait(timeout=0.35)
        assert time.monotonic() - released_at < 0.35
    finally:
        if not first._released:
            first.release()
        thread.join(timeout=3)
        if not thread.is_alive():
            controller.close()
            controller._test_registry.close()
    assert not thread.is_alive()
    assert errors == []


class _CountingCancellation:
    def __init__(self) -> None:
        from noetrium_platform.foundation.kernel.concurrency.runtime.cancellation import (
            _CancellationState,
        )
        self._token = _CancellationState()
        self.subscriptions = 0
        self.unsubscriptions = 0

    @property
    def cancelled(self) -> bool:
        return self._token.cancelled

    @property
    def reason(self) -> str | None:
        return self._token.reason

    def subscribe_cancel(self, callback):
        self.subscriptions += 1
        unsubscribe = self._token.subscribe_cancel(callback)

        def release() -> None:
            self.unsubscriptions += 1
            unsubscribe()

        return release

    def cancel(self, reason: str) -> bool:
        return self._token.cancel(reason)


def test_contended_model_request_subscribes_cancellation_only_once() -> None:
    controller = make_model_admission_controller(1)
    holder = controller.acquire(owner_id="holder")
    token = _CountingCancellation()
    counted = _CountAuthority(controller._authority)
    controller._authority = counted
    try:
        with pytest.raises(ModelAdmissionTimeout):
            controller.acquire(
                owner_id="blocked", timeout_seconds=0.28,
                cancellation=token,
            )
        assert counted.attempts >= 4
        assert token.subscriptions == 1
        assert token.unsubscriptions == 1
        assert controller.snapshot().waiting == 0
    finally:
        holder.release()
        controller.close()
        controller._test_registry.close()


def test_uncontended_model_request_does_not_subscribe_cancellation() -> None:
    controller = make_model_admission_controller(1)
    token = _CountingCancellation()
    try:
        with controller.acquire(owner_id="fast", cancellation=token):
            assert token.subscriptions == 0
        assert token.unsubscriptions == 0
    finally:
        controller.close()
        controller._test_registry.close()


def test_cancelled_model_request_wakes_after_multiple_backoff_rounds() -> None:
    controller = make_model_admission_controller(1)
    holder = controller.acquire(owner_id="holder")
    token = _CountingCancellation()
    counted = _CountAuthority(controller._authority)
    controller._authority = counted
    errors: list[BaseException] = []
    cancelled = Event()

    def waiter() -> None:
        try:
            controller.acquire(owner_id="blocked", cancellation=token)
        except BaseException as exc:
            errors.append(exc)
        finally:
            cancelled.set()

    thread = Thread(target=waiter, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 2
        while counted.attempts < 4 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert counted.attempts >= 4
        assert token.subscriptions == 1
        start = time.monotonic()
        token.cancel("stop waiting for model")
        assert cancelled.wait(0.5)
        assert time.monotonic() - start < 0.5
        assert len(errors) == 1
        from noetrium_platform.foundation.kernel.concurrency.api import TaskCancelled
        assert isinstance(errors[0], TaskCancelled)
        assert token.unsubscriptions == 1
    finally:
        token.cancel("ensure stop")
        thread.join(timeout=2)
        holder.release()
        controller.close()
        controller._test_registry.close()


def test_continuity_borrow_subscribes_once_across_repeated_conflicts() -> None:
    controller = make_model_admission_controller(1)
    controller.qualify_continuity(1)
    reservation = controller.try_reserve_continuity(
        owner_id="paper", flow_id="lifespan",
    )
    assert reservation is not None
    active = controller.acquire(
        owner_id="paper",
        continuity_claim_id=reservation.claim_id,
        timeout_seconds=0.2,
    )
    token = _CountingCancellation()
    counted = _CountAuthority(controller._authority)
    controller._authority = counted
    try:
        with pytest.raises(ModelAdmissionTimeout):
            controller.acquire(
                owner_id="paper",
                continuity_claim_id=reservation.claim_id,
                timeout_seconds=0.28,
                cancellation=token,
            )
        assert counted.attempts >= 4
        assert token.subscriptions == 1
        assert token.unsubscriptions == 1
    finally:
        active.release()
        reservation.release()
        controller.close()
        controller._test_registry.close()


def test_spurious_local_notifications_do_not_reset_remote_conflict_backoff() -> None:
    controller = make_model_admission_controller(1)
    holder = controller.acquire(owner_id="holder")
    counted = _CountAuthority(controller._authority)
    controller._authority = counted
    stop = Event()

    def send_unrelated_notifications() -> None:
        while not stop.is_set():
            with controller._cv:
                controller._cv.notify_all()
            time.sleep(0.002)

    notifier = Thread(target=send_unrelated_notifications, daemon=True)
    notifier.start()
    try:
        with pytest.raises(ModelAdmissionTimeout):
            controller.acquire(owner_id="blocked", timeout_seconds=0.28)
        # There are many local notifications, but no actual local release.
        # They must neither clear the exponential backoff nor create a
        # fresh SQLite admission transaction per notification.
        assert 3 <= counted.attempts <= 11, counted.attempts
    finally:
        stop.set()
        notifier.join(timeout=2)
        holder.release()
        controller.close()
        controller._test_registry.close()


def test_local_release_between_conflict_and_wait_never_loses_wakeup(
    monkeypatch,
) -> None:
    from noetrium_platform.substrate.api import ResourceClaimConflict

    controller = make_model_admission_controller(1)
    holder = controller.acquire(owner_id="holder")
    authority = controller._authority
    released = Event()

    class _RacedAuthority:
        def admit_bundle(self, groups):
            try:
                return authority.admit_bundle(groups)
            except ResourceClaimConflict:
                if not released.is_set():
                    holder.release()
                    released.set()
                raise

        def __getattr__(self, name):
            return getattr(authority, name)

    controller._authority = _RacedAuthority()

    def forbidden_wait(_timeout=None):
        raise AssertionError(
            "local release raced with Authority conflict, must recheck immediately"
        )

    monkeypatch.setattr(controller._cv, "wait", forbidden_wait)
    try:
        with controller.acquire(owner_id="retry", timeout_seconds=1.0):
            assert released.is_set()
    finally:
        if not holder._released:
            holder.release()
        controller.close()
        controller._test_registry.close()
