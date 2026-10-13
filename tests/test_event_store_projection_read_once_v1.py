"""Durable State readers must not replay one causal journal twice per lookup."""
from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.capabilities.model.deployment.runtime import AppliedModelDeploymentStore
from noetrium_platform.capabilities.model.deployment.runtime.applied_store import _AppliedProjection
from noetrium_platform.foundation.kernel.event_store import FileCausalEventStore
from noetrium_platform.infrastructure.lifecycle.python.runtime.registry import PythonEnvironmentRegistry
from noetrium_platform.infrastructure.lifecycle.python.runtime.lifecycle_transaction import (
    PythonEnvironmentLifecycleTransactionStore,
)


class _Directories:
    def __init__(self, root: Path) -> None:
        self._root = root

    def root(self, kind):
        path = self._root / str(kind.value)
        path.mkdir(parents=True, exist_ok=True)
        return path


def test_applied_model_projection_lookup_replays_single_time(tmp_path, monkeypatch) -> None:
    store = AppliedModelDeploymentStore(_Directories(tmp_path))
    journal = store._journal("model")
    journal.append(json.dumps({
        "schema": "noetrium.model-applied-projection.v3", "active": None, "cleared": [],
    }).encode())
    original = FileCausalEventStore._scan_events_unlocked
    scans = []

    def counted(self, *, collect):
        scans.append(True)
        return original(self, collect=collect)

    monkeypatch.setattr(FileCausalEventStore, "_scan_events_unlocked", counted)
    assert store._journal("model") is store._journal("model")
    assert store._read_projection("model").active is None
    assert len(scans) == 1
    store._append_projection("model", _AppliedProjection(None, ()), phase="model-cleared")
    assert len(scans) == 1


def test_absent_python_environment_journals_do_not_require_exists_scan(tmp_path, monkeypatch) -> None:
    directories = _Directories(tmp_path)
    registry = PythonEnvironmentRegistry(directories)
    lifecycle = PythonEnvironmentLifecycleTransactionStore(directories)
    assert registry._journal("missing") is registry._journal("missing")
    assert lifecycle._journal("missing") is lifecycle._journal("missing")
    original = FileCausalEventStore._scan_events_unlocked
    scans = []

    def counted(self, *, collect):
        scans.append(True)
        return original(self, collect=collect)

    monkeypatch.setattr(FileCausalEventStore, "_scan_events_unlocked", counted)
    assert registry._latest("missing") is None
    assert lifecycle.latest("missing") is None
    assert len(scans) == 2
