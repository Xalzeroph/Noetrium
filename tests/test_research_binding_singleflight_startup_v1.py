"""Repeated Study consumers must borrow one immutable binding resolution."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock, RLock
from time import sleep
from types import SimpleNamespace

import pytest

import noetrium_platform.composition.research_binding_authority as mod


def _authority(monkeypatch, *, fail_first=False):
    entered = Event()
    release = Event()
    mu = Lock()
    calls = [0]

    class Manifests:
        def resolve(self, _definition):
            with mu:
                calls[0] += 1
                current = calls[0]
            entered.set()
            if not release.wait(timeout=4):
                raise TimeoutError("test manifest source was not released")
            if fail_first and current == 1:
                raise LookupError("manifest unavailable")
            return object()

    owner = object.__new__(mod.ResearchBindingAuthority)
    owner._manifests = Manifests()
    owner._cache = {}
    owner._cache_lock = RLock()
    owner._inflight = {}
    owner._model_bindings = lambda _context: ((), ())
    owner._capability_bindings = lambda _context: ()
    owner._participant_bindings = lambda _context: ()
    monkeypatch.setattr(mod, "require_study_unit", lambda _definition: None)
    monkeypatch.setattr(mod, "study_definition_digest", lambda _definition: "study-cut")
    monkeypatch.setattr(mod, "require_project_manifest", lambda _manifest: None)
    monkeypatch.setattr(
        mod, "resolve_research_requirements",
        lambda _definition, _manifest: SimpleNamespace(resolution_digest="resolution"),
    )
    monkeypatch.setattr(
        mod.ResearchBindingResolutionContext, "create",
        staticmethod(lambda *_args: object()),
    )
    monkeypatch.setattr(
        mod, "ResearchBindingContribution",
        lambda digest, capabilities, participants, models, gaps:
            (digest, capabilities, participants, models, gaps),
    )
    monkeypatch.setattr(
        mod, "validate_research_binding_contribution", lambda *_args: None,
    )
    return owner, entered, release, calls


def test_parallel_same_study_resolves_once_with_exact_shared_closure(monkeypatch):
    owner, entered, release, calls = _authority(monkeypatch)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(owner.resolve, object())
        assert entered.wait(timeout=3)
        duplicate_a = pool.submit(owner.resolve, object())
        duplicate_b = pool.submit(owner.resolve, object())
        sleep(0.05)
        assert calls == [1]
        assert not duplicate_a.done()
        assert not duplicate_b.done()
        release.set()
        expected = first.result(timeout=3)
        assert duplicate_a.result(timeout=3) is expected
        assert duplicate_b.result(timeout=3) is expected
    assert calls == [1]
    assert not owner._inflight
    assert owner.resolve(object()) is expected


def test_failed_producer_fails_waiters_and_allows_clean_retry(monkeypatch):
    owner, entered, release, calls = _authority(monkeypatch, fail_first=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(owner.resolve, object())
        assert entered.wait(timeout=3)
        duplicate = pool.submit(owner.resolve, object())
        sleep(0.05)
        assert calls == [1]
        release.set()
        with pytest.raises(LookupError, match="manifest unavailable"):
            first.result(timeout=3)
        with pytest.raises(LookupError, match="manifest unavailable"):
            duplicate.result(timeout=3)
    assert calls == [1]
    assert not owner._cache
    assert not owner._inflight
    assert owner.resolve(object())[0].resolution_digest == "resolution"
    assert calls == [2]
