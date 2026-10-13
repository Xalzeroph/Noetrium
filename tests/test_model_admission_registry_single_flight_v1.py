"""Per-deployment controller creation is single-flight and close-drained."""
from __future__ import annotations

from threading import Event, Lock, Thread
import time

import pytest

from model_admission_test_support import make_model_admission_registry
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionClosed
import noetrium_platform.capabilities.model.serving.runtime.admission as admission


class _Controller:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.closed = False

    def qualify_continuity(self, capacity: int) -> None:
        if capacity > self.capacity:
            raise ValueError("continuity qualification exceeds capacity")

    def close(self) -> None:
        self.closed = True


def _invoke(registry, key: str, results: list, failures: list) -> None:
    try:
        results.append(registry.controller_for(
            deployment_id=key,
            deployment_generation="a" * 64,
            qualified_capacity=2,
        ))
    except BaseException as exc:
        failures.append(exc)


def test_distinct_deployments_construct_concurrently(monkeypatch) -> None:
    registry = make_model_admission_registry()
    entered = Event()
    release = Event()
    guard = Lock()
    created: list[str] = []

    def construct(_authority, _lease, *, deployment_id, qualified_capacity, **_kwargs):
        with guard:
            created.append(deployment_id)
            if len(created) == 2:
                entered.set()
        if not release.wait(5):
            raise AssertionError("different deployments serialized behind registry")
        return _Controller(qualified_capacity)

    monkeypatch.setattr(admission, "ModelAdmissionController", construct)
    results: list = []
    failures: list = []
    threads = [
        Thread(target=_invoke, args=(registry, name, results, failures), daemon=True)
        for name in ("model-a", "model-b")
    ]
    try:
        for thread in threads:
            thread.start()
        assert entered.wait(3), "distinct model constructions did not overlap"
    finally:
        release.set()
        for thread in threads:
            thread.join(3)
    assert all(not thread.is_alive() for thread in threads)
    assert failures == []
    assert len(results) == 2
    assert len(set(created)) == 2
    registry.close()
    assert all(result.closed for result in results)


def test_same_deployment_is_constructed_once(monkeypatch) -> None:
    registry = make_model_admission_registry()
    constructing = Event()
    release = Event()
    count = []

    def construct(_authority, _lease, *, qualified_capacity, **_kwargs):
        count.append(True)
        constructing.set()
        if not release.wait(5):
            raise AssertionError("single-flight constructor did not resume")
        return _Controller(qualified_capacity)

    monkeypatch.setattr(admission, "ModelAdmissionController", construct)
    results: list = []
    failures: list = []
    threads = [
        Thread(target=_invoke, args=(registry, "shared", results, failures), daemon=True)
        for _ in range(4)
    ]
    try:
        for thread in threads:
            thread.start()
        assert constructing.wait(3)
        time.sleep(0.05)
        assert len(count) == 1
    finally:
        release.set()
        for thread in threads:
            thread.join(3)
    assert all(not thread.is_alive() for thread in threads)
    assert failures == []
    assert len(results) == 4
    assert all(result is results[0] for result in results)
    registry.close()


def test_close_waits_for_inflight_controller_construction(monkeypatch) -> None:
    registry = make_model_admission_registry()
    constructing = Event()
    release = Event()
    created: list[_Controller] = []

    def construct(_authority, _lease, *, qualified_capacity, **_kwargs):
        constructing.set()
        if not release.wait(5):
            raise AssertionError("blocked constructor was not released")
        controller = _Controller(qualified_capacity)
        created.append(controller)
        return controller

    monkeypatch.setattr(admission, "ModelAdmissionController", construct)
    results: list = []
    failures: list = []
    request = Thread(target=_invoke, args=(registry, "shared", results, failures), daemon=True)
    closing = Thread(target=registry.close, daemon=True)
    request.start()
    try:
        assert constructing.wait(3)
        closing.start()
        closing.join(0.05)
        assert closing.is_alive(), "Registry closed before construction completed"
    finally:
        release.set()
        request.join(3)
        closing.join(3)
    assert not request.is_alive()
    assert not closing.is_alive()
    assert failures == []
    assert len(created) == 1
    assert created[0].closed
    assert registry.closed
    with pytest.raises(ModelAdmissionClosed):
        registry.controller_for(
            deployment_id="too-late", deployment_generation="b" * 64,
            qualified_capacity=1,
        )


def test_registry_does_not_cache_failed_controller_construction(monkeypatch) -> None:
    registry = make_model_admission_registry()
    attempts: list[int] = []

    def construct(_authority, _lease, *, qualified_capacity, **_kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("injected transient qualification error")
        return _Controller(qualified_capacity)

    monkeypatch.setattr(admission, "ModelAdmissionController", construct)
    with pytest.raises(RuntimeError, match="transient qualification"):
        registry.controller_for(
            deployment_id="retriable", deployment_generation="a" * 64,
            qualified_capacity=2,
        )
    controller = registry.controller_for(
        deployment_id="retriable", deployment_generation="a" * 64,
        qualified_capacity=2,
    )
    assert len(attempts) == 2
    assert not controller.closed
    registry.close()
    assert controller.closed


def test_close_drains_inflight_continuity_qualification(monkeypatch) -> None:
    registry = make_model_admission_registry()
    started, resume = Event(), Event()
    qualified: list[_Controller] = []

    class _SlowController(_Controller):
        def qualify_continuity(self, capacity: int) -> None:
            started.set()
            if not resume.wait(5):
                raise AssertionError("qualification timed out")
            super().qualify_continuity(capacity)

    def construct(_authority, _lease, *, qualified_capacity, **_kwargs):
        result = _SlowController(qualified_capacity)
        qualified.append(result)
        return result

    monkeypatch.setattr(admission, "ModelAdmissionController", construct)
    errors: list[BaseException] = []

    def worker():
        try:
            registry.controller_for(
                deployment_id="qualification", deployment_generation="a" * 64,
                qualified_capacity=2, continuity_capacity=1,
            )
        except BaseException as exc:
            errors.append(exc)

    lookup = Thread(target=worker, daemon=True)
    closing = Thread(target=registry.close, daemon=True)
    lookup.start()
    try:
        assert started.wait(3)
        closing.start()
        closing.join(0.05)
        assert closing.is_alive()
    finally:
        resume.set()
        lookup.join(3)
        closing.join(3)
    assert not lookup.is_alive()
    assert not closing.is_alive()
    assert errors == []
    assert len(qualified) == 1
    assert qualified[0].closed
    assert registry.closed
