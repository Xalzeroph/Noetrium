from __future__ import annotations

from pathlib import Path

import pytest

import noetrium_platform.research.experimentation.lifecycle.run.runtime.artifacts as artifacts_runtime
from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierClosureAuthority,
    DurableCarrierReferenceClosure,
)
from noetrium_platform.research.experimentation.lifecycle.api import (
    RunArtifactKind,
    RunArtifactSealedError,
)
from noetrium_platform.research.experimentation.lifecycle.run.runtime import (
    DirectoryRunArtifactStore,
)


class _InlineSerialActor:
    actor_id = "run-artifact-gc-test"

    def call(self, operation, fn, /, *args, **kwargs):
        del operation, kwargs
        return fn(*args)


def _store(path: Path) -> DirectoryRunArtifactStore:
    return DirectoryRunArtifactStore(
        path,
        run_id="run-gc",
        writer_actor=_InlineSerialActor(),
    )


def _closed(
    *,
    evidence: str = "a",
    execution: str = "b",
    recovery: str = "c",
) -> tuple[DurableCarrierReferenceClosure, ...]:
    return (
        DurableCarrierReferenceClosure(
            DurableCarrierClosureAuthority.EVIDENCE,
            evidence * 64,
            (),
        ),
        DurableCarrierReferenceClosure(
            DurableCarrierClosureAuthority.EXECUTION,
            execution * 64,
            (),
        ),
        DurableCarrierReferenceClosure(
            DurableCarrierClosureAuthority.RECOVERY,
            recovery * 64,
            (),
        ),
    )


def _populated(tmp_path: Path) -> DirectoryRunArtifactStore:
    store = _store(tmp_path / "run-artifacts" / "cut-1")
    store.publish_text(
        "evidence/events.jsonl",
        '{"event":1}\n',
        kind=RunArtifactKind.EVIDENCE,
    )
    store.publish_text(
        "result/summary.json",
        '{"status":"ok"}\n',
        kind=RunArtifactKind.RESULT,
    )
    return store


def test_run_artifact_gc_fails_closed_without_complete_closure(
    tmp_path: Path,
) -> None:
    store = _populated(tmp_path)
    partial = store.assess_gc(
        closures=(
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.EXECUTION,
                "d" * 64,
                (),
            ),
        ),
    )
    assert not partial.closure_complete
    assert not partial.eligible
    with pytest.raises(
        RuntimeError,
        match="complete execution, evidence, and recovery",
    ):
        store.purge(gc=partial)
    assert (store.root / "evidence" / "events.jsonl").is_file()


@pytest.mark.parametrize(
    ("authority", "reference"),
    (
        (DurableCarrierClosureAuthority.EVIDENCE, "evidence-retained"),
        (DurableCarrierClosureAuthority.EXECUTION, "run-resumable"),
        (DurableCarrierClosureAuthority.RECOVERY, "checkpoint-retained"),
    ),
)
def test_run_artifact_gc_blocks_each_retained_reference_authority(
    tmp_path: Path,
    authority: DurableCarrierClosureAuthority,
    reference: str,
) -> None:
    store = _populated(tmp_path)
    closures = tuple(
        DurableCarrierReferenceClosure(
            current,
            digest * 64,
            (reference,) if current is authority else (),
        )
        for current, digest in (
            (DurableCarrierClosureAuthority.EVIDENCE, "4"),
            (DurableCarrierClosureAuthority.EXECUTION, "5"),
            (DurableCarrierClosureAuthority.RECOVERY, "6"),
        )
    )
    gc = store.assess_gc(closures=closures)
    assert gc.closure_complete
    assert not gc.eligible
    with pytest.raises(RuntimeError, match="zero retained references"):
        store.purge(gc=gc)
    assert store.root.is_dir()


def test_run_artifact_gc_rejects_tree_change_after_assessment(
    tmp_path: Path,
) -> None:
    store = _populated(tmp_path)
    gc = store.assess_gc(closures=_closed())
    store.publish_text(
        "result/late.json",
        '{"late":true}\n',
        kind=RunArtifactKind.RESULT,
    )
    with pytest.raises(RuntimeError, match="changed after GC assessment"):
        store.purge(gc=gc)
    assert (store.root / "result" / "late.json").is_file()


def test_run_artifact_gc_is_terminal_and_idempotent(
    tmp_path: Path,
) -> None:
    store = _populated(tmp_path)
    closures = _closed()
    gc = store.assess_gc(closures=closures)
    assert gc.eligible
    assert store.purge(gc=gc)
    assert not store.root.exists()

    with pytest.raises(RunArtifactSealedError, match="carrier identity is retired"):
        store.publish_text(
            "result/reappeared.json",
            "{}",
            kind=RunArtifactKind.RESULT,
        )

    retry = store.assess_gc(closures=closures)
    assert retry == gc
    assert store.purge(gc=retry)
    assert not store.root.exists()


def test_run_artifact_gc_recovers_rename_commit_before_phase_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _populated(tmp_path)
    gc = store.assess_gc(closures=_closed())
    real_publish = artifacts_runtime.atomic_replace_bytes
    calls = 0

    def fail_second(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("crash after run-artifact quarantine rename")
        real_publish(path, payload)

    monkeypatch.setattr(artifacts_runtime, "atomic_replace_bytes", fail_second)
    with pytest.raises(OSError, match="after run-artifact quarantine"):
        store.purge(gc=gc)

    quarantine = store._quarantine_path()
    assert not store.root.exists()
    assert quarantine.is_dir()
    assert (quarantine / "evidence" / "events.jsonl").is_file()

    monkeypatch.setattr(artifacts_runtime, "atomic_replace_bytes", real_publish)
    assert store.purge(gc=gc)
    assert not quarantine.exists()


def test_run_artifact_gc_recovers_recursive_delete_before_terminal_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _populated(tmp_path)
    gc = store.assess_gc(closures=_closed())
    real_publish = artifacts_runtime.atomic_replace_bytes
    calls = 0

    def fail_third(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("crash after run-artifact physical purge")
        real_publish(path, payload)

    monkeypatch.setattr(artifacts_runtime, "atomic_replace_bytes", fail_third)
    with pytest.raises(OSError, match="after run-artifact physical purge"):
        store.purge(gc=gc)

    assert not store.root.exists()
    assert not store._quarantine_path().exists()

    monkeypatch.setattr(artifacts_runtime, "atomic_replace_bytes", real_publish)
    assert store.purge(gc=gc)


def test_run_artifact_gc_retries_partial_recursive_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _populated(tmp_path)
    gc = store.assess_gc(closures=_closed())
    real_rmtree = artifacts_runtime.shutil.rmtree
    calls = 0

    def partial_then_fail(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            victim = path / "result" / "summary.json"
            victim.unlink()
            raise OSError("partial recursive delete interruption")
        real_rmtree(path)

    monkeypatch.setattr(artifacts_runtime.shutil, "rmtree", partial_then_fail)
    with pytest.raises(OSError, match="partial recursive"):
        store.purge(gc=gc)

    quarantine = store._quarantine_path()
    assert quarantine.is_dir()
    assert not (quarantine / "result" / "summary.json").exists()
    assert (quarantine / "evidence" / "events.jsonl").is_file()

    monkeypatch.setattr(artifacts_runtime.shutil, "rmtree", real_rmtree)
    assert store.purge(gc=gc)
    assert not quarantine.exists()


def test_run_artifact_gc_retry_rejects_changed_closure_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _populated(tmp_path)
    original = store.assess_gc(closures=_closed())
    real_publish = artifacts_runtime.atomic_replace_bytes
    calls = 0

    def fail_second(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("crash after durable run-artifact retirement")
        real_publish(path, payload)

    monkeypatch.setattr(artifacts_runtime, "atomic_replace_bytes", fail_second)
    with pytest.raises(OSError, match="after durable run-artifact retirement"):
        store.purge(gc=original)

    monkeypatch.setattr(artifacts_runtime, "atomic_replace_bytes", real_publish)
    changed = store.assess_gc(
        closures=_closed(evidence="d", execution="e", recovery="f"),
    )
    with pytest.raises(RuntimeError, match="GC proof changed across retry"):
        store.purge(gc=changed)

    assert store.purge(gc=original)


def test_run_artifact_gc_rejects_split_truth_after_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _populated(tmp_path)
    gc = store.assess_gc(closures=_closed())
    real_publish = artifacts_runtime.atomic_replace_bytes
    calls = 0

    def fail_second(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("phase publication lost")
        real_publish(path, payload)

    monkeypatch.setattr(artifacts_runtime, "atomic_replace_bytes", fail_second)
    with pytest.raises(OSError, match="phase publication lost"):
        store.purge(gc=gc)

    quarantine = store._quarantine_path()
    store.root.mkdir(parents=True)
    foreign = store.root / "foreign-new-lifetime"
    foreign.write_text("do-not-delete", encoding="utf-8")

    monkeypatch.setattr(artifacts_runtime, "atomic_replace_bytes", real_publish)
    with pytest.raises(RuntimeError, match="split live/quarantine truth"):
        store.purge(gc=gc)

    assert foreign.read_text("utf-8") == "do-not-delete"
    assert quarantine.is_dir()


def test_retirement_fence_prevents_stale_writer_from_recreating_live_root(
    tmp_path: Path,
) -> None:
    store = _populated(tmp_path)
    gc = store.assess_gc(closures=_closed())
    assert store.purge(gc=gc)

    reopened = _store(store.root)
    with pytest.raises(RunArtifactSealedError, match="carrier identity is retired"):
        reopened.append_json(
            "evidence/events.jsonl",
            {"event": 2},
            kind=RunArtifactKind.EVIDENCE,
        )
    assert not store.root.exists()
