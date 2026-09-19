from __future__ import annotations

import json
from pathlib import Path

import pytest

from noetrium_platform.evidence.observability.logging.context.api import DiagnosticAddress
from noetrium_platform.evidence.observability.logging.record.api import LogLevel, LogRecord
import noetrium_platform.evidence.observability.logging.storage.runtime.jsonl as jsonl_runtime
from noetrium_platform.evidence.observability.logging.storage.runtime.jsonl import (
    JsonlLogCorruptionError,
    JsonlLogStore as RuntimeJsonlLogStore,
)
from tests._concurrency_support import jsonl_log_store as JsonlLogStore
from noetrium_platform.evidence.observability.logging.storage.composition import build_jsonl_log_store
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE


def _record(index: int) -> LogRecord:
    return LogRecord(
        f"log-{index}",
        float(index),
        LogLevel.INFO,
        "test",
        "event",
        "safe",
        DiagnosticAddress((PLATFORM_SCOPE,)),
    )


def test_jsonl_store_uses_structural_logging_ports_without_nominal_bases() -> None:
    from noetrium_platform.evidence.observability.logging.query.api import LogQueryPort
    from noetrium_platform.evidence.observability.logging.sink.api import LogSinkPort

    assert LogQueryPort not in RuntimeJsonlLogStore.__mro__
    assert LogSinkPort not in RuntimeJsonlLogStore.__mro__
    assert callable(RuntimeJsonlLogStore.append)
    assert callable(RuntimeJsonlLogStore.query)


def test_query_reads_pinned_snapshot_when_rotation_wins_after_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "events.jsonl"
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group("jsonl-pinned-snapshot-rotation")
    try:
        store = build_jsonl_log_store(path, task_group=group, max_bytes=1, max_segments=2)
        store.append(_record(1))
        original = RuntimeJsonlLogStore._iter_frozen_lines
        rotated = {"done": False}

        def rotate_after_freeze(snapshot):
            if not rotated["done"]:
                rotated["done"] = True
                store.append(_record(2))
            yield from original(snapshot)

        monkeypatch.setattr(
            RuntimeJsonlLogStore,
            "_iter_frozen_lines",
            staticmethod(rotate_after_freeze),
        )
        assert [row.log_id for row in store.query(limit=10)] == ["log-1"]
        assert rotated["done"] is True
        assert path.is_file()
        assert len(tuple(tmp_path.glob("events.jsonl.segment.*"))) == 1
    finally:
        runtime.close()


def test_query_pinned_handle_read_failure_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = JsonlLogStore(tmp_path / "events.jsonl")
    store.append(_record(1))
    attempts = {"count": 0}

    def denied(snapshot):
        del snapshot
        attempts["count"] += 1
        raise PermissionError(13, "persistent pinned-handle read failure")
        yield

    monkeypatch.setattr(RuntimeJsonlLogStore, "_iter_frozen_lines", staticmethod(denied))
    with pytest.raises(PermissionError, match="pinned-handle"):
        store.query(limit=10)
    assert attempts["count"] == 1

def test_store_keeps_logical_path_identity_if_live_leaf_resolution_drifts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "events.jsonl"
    rival = tmp_path / "events.jsonl.1"
    original_resolve = Path.resolve

    def drifting_resolve(candidate: Path, *args, **kwargs):
        if candidate == path:
            return rival
        return original_resolve(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", drifting_resolve)
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group("jsonl-logical-path-regression")
    try:
        store = build_jsonl_log_store(path, task_group=group, max_bytes=700, max_segments=8)
        assert store.path == path
        assert store._guard_path == path.with_name("events.jsonl.guard.lock")
        store.append(_record(1))
        assert path.is_file()
        assert not rival.exists()
    finally:
        runtime.close()


def _generation_segments(root: Path, generation: int) -> tuple[Path, ...]:
    return tuple(sorted(root.glob(
        f"events.jsonl.segment.{generation:020d}.*"
    )))


def test_query_limit_returns_globally_newest_records_without_rotation(tmp_path: Path) -> None:
    store = JsonlLogStore(tmp_path / "events.jsonl")
    for index in range(5):
        store.append(_record(index))
    assert [row.log_id for row in store.query(limit=3)] == ["log-4", "log-3", "log-2"]


def test_query_limit_returns_globally_newest_records_across_segments(tmp_path: Path) -> None:
    store = JsonlLogStore(tmp_path / "events.jsonl", max_bytes=1, max_segments=4)
    for index in range(5):
        store.append(_record(index))
    assert [row.log_id for row in store.query(limit=3)] == ["log-4", "log-3", "log-2"]
    assert len(_generation_segments(tmp_path, 4)) == 1


def test_rotation_generation_not_mtime_controls_retention(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlLogStore(path, max_bytes=1, max_segments=2)
    store.append(_record(0))
    store.append(_record(1))
    store.append(_record(2))
    (first,) = _generation_segments(tmp_path, 1)
    (second,) = _generation_segments(tmp_path, 2)
    collision_ns = 1_700_000_000_000_000_000
    import os
    os.utime(first, ns=(collision_ns, collision_ns))
    os.utime(second, ns=(collision_ns, collision_ns))

    store.append(_record(3))

    (third,) = _generation_segments(tmp_path, 3)
    assert not first.exists()
    assert second.is_file()
    assert third.is_file()
    assert [row.log_id for row in store.query(limit=3)] == ["log-3", "log-2", "log-1"]


def test_rotation_restart_recovers_monotonic_generation_order(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    first_store = JsonlLogStore(path, max_bytes=1, max_segments=8)
    for index in range(3):
        first_store.append(_record(index))
    assert len(_generation_segments(tmp_path, 1)) == 1
    assert len(_generation_segments(tmp_path, 2)) == 1

    restarted_store = JsonlLogStore(path, max_bytes=1, max_segments=8)
    restarted_store.append(_record(3))

    assert len(_generation_segments(tmp_path, 3)) == 1
    assert [row.log_id for row in restarted_store.query(limit=10)] == [
        "log-3", "log-2", "log-1", "log-0"
    ]


def test_duplicate_immutable_generation_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlLogStore(path, max_bytes=1, max_segments=8)
    store.append(_record(0))
    store.append(_record(1))
    (published,) = _generation_segments(tmp_path, 1)
    duplicate = tmp_path / (
        "events.jsonl.segment.00000000000000000001." + "f" * 32
    )
    duplicate.write_bytes(published.read_bytes())

    with pytest.raises(JsonlLogCorruptionError, match="duplicate or invalid"):
        store.query(limit=10)


def test_rotation_prune_failure_preserves_published_generations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlLogStore(path, max_bytes=1, max_segments=1)
    store.append(_record(0))
    store.append(_record(1))

    def fail_prune(_path: Path) -> None:
        raise OSError("simulated prune crash")

    monkeypatch.setattr(jsonl_runtime, "durable_unlink", fail_prune)
    with pytest.raises(OSError, match="simulated prune crash"):
        store.append(_record(2))

    assert not path.exists()
    assert len(_generation_segments(tmp_path, 1)) == 1
    assert len(_generation_segments(tmp_path, 2)) == 1
    assert {row.log_id for row in store.query(limit=10)} == {"log-0", "log-1"}


def test_rotation_publication_failure_keeps_active_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlLogStore(path, max_bytes=1, max_segments=2)
    store.append(_record(0))
    before = path.read_bytes()

    def fail_publish(_source: Path, _target: Path) -> None:
        raise OSError("simulated pre-publication crash")

    monkeypatch.setattr(jsonl_runtime, "durable_replace_file", fail_publish)
    with pytest.raises(OSError, match="simulated pre-publication crash"):
        store.append(_record(1))

    assert path.read_bytes() == before
    assert tuple(tmp_path.glob("events.jsonl.segment.*")) == ()


def test_malformed_immutable_segment_generation_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlLogStore(path)
    store.append(_record(0))
    (tmp_path / "events.jsonl.segment.not-a-generation").write_bytes(b"{}\n")
    with pytest.raises(JsonlLogCorruptionError, match="malformed immutable JSONL segment generation"):
        store.query(limit=10)


def test_wrong_schema_is_corruption_not_silently_decoded(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlLogStore(path)
    store.append(_record(1))
    row = json.loads(path.read_text(encoding="utf-8"))
    row["schema_version"] = "wrong.schema"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(JsonlLogCorruptionError):
        store.query()


def test_wrong_persisted_scalar_types_are_corruption_not_coerced(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlLogStore(path)
    store.append(_record(1))
    row = json.loads(path.read_text(encoding="utf-8"))
    row["log_id"] = 123
    row["correlation_refs"] = [99]
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(JsonlLogCorruptionError):
        store.query()


def test_wrong_persisted_attribute_shape_is_typed_corruption(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlLogStore(path)
    store.append(_record(1))
    row = json.loads(path.read_text(encoding="utf-8"))
    row["attributes"] = ["a"]
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(JsonlLogCorruptionError):
        store.query()


def test_log_record_rejects_non_finite_timestamp_before_persistence() -> None:
    with pytest.raises(ValueError, match="finite"):
        LogRecord(
            "log-nan",
            float("nan"),
            LogLevel.INFO,
            "test",
            "event",
            "safe",
            DiagnosticAddress((PLATFORM_SCOPE,)),
        )


def test_duplicate_json_object_keys_are_complete_line_corruption(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlLogStore(path)
    store.append(_record(1))
    line = path.read_text(encoding="utf-8")
    line = line.replace('"log_id":"log-1"', '"log_id":"log-1","log_id":"log-1"', 1)
    path.write_text(line, encoding="utf-8")
    with pytest.raises(JsonlLogCorruptionError):
        store.query()


def test_jsonl_storage_uses_single_byte_newlines_for_byte_precise_rotation(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlLogStore(path)
    store.append(_record(1))
    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\r\n")


def _append_worker(path: str, worker: int, count: int) -> None:
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group(f"multiprocess-log-writer:{worker}")
    store = build_jsonl_log_store(path, task_group=group, max_bytes=700, max_segments=64)
    try:
        for offset in range(count):
            index = worker * 1000 + offset
            store.append(_record(index))
    finally:
        runtime.close()


def test_multiple_processes_append_and_rotate_without_overwrite(tmp_path: Path) -> None:
    import multiprocessing

    path = tmp_path / "events.jsonl"
    context = multiprocessing.get_context("spawn")
    processes = [context.Process(target=_append_worker, args=(str(path), worker, 12)) for worker in range(4)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    rows = JsonlLogStore(path, max_bytes=700, max_segments=64).query(limit=1000)
    assert len(rows) == 48
    assert len({row.log_id for row in rows}) == 48


def _append_pruning_worker(path: str, worker: int, count: int) -> None:
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group(f"multiprocess-log-pruner:{worker}")
    store = build_jsonl_log_store(path, task_group=group, max_bytes=700, max_segments=4)
    try:
        for offset in range(count):
            index = worker * 1000 + offset
            store.append(_record(index))
    finally:
        runtime.close()


def test_multiple_processes_rotate_and_prune_monotonic_generations(tmp_path: Path) -> None:
    import multiprocessing

    path = tmp_path / "events.jsonl"
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_append_pruning_worker, args=(str(path), worker, 12))
        for worker in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0

    segments = sorted(tmp_path.glob("events.jsonl.segment.*"))
    assert 1 <= len(segments) <= 4
    generations = sorted(
        int(segment.name.split(".segment.", 1)[1].split(".", 1)[0])
        for segment in segments
    )
    assert len(generations) == len(set(generations))
    assert generations == list(range(generations[0], generations[-1] + 1))
    rows = JsonlLogStore(path, max_bytes=700, max_segments=4).query(limit=1000)
    assert len({row.log_id for row in rows}) == len(rows)


def _query_worker(path: str, stop) -> None:
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group("multiprocess-log-reader")
    store = build_jsonl_log_store(path, task_group=group, max_bytes=700, max_segments=64)
    try:
        while not stop.wait(0.001):
            rows = store.query(limit=1000)
            ids = [row.log_id for row in rows]
            if len(ids) != len(set(ids)):
                raise AssertionError("concurrent JSONL query returned duplicate log identities")
    finally:
        runtime.close()


def test_multiple_processes_rotate_while_concurrent_readers_query(tmp_path: Path) -> None:
    import multiprocessing

    path = tmp_path / "events.jsonl"
    context = multiprocessing.get_context("spawn")
    stop = context.Event()
    readers = [
        context.Process(target=_query_worker, args=(str(path), stop)) for _ in range(2)
    ]
    writers = [
        context.Process(target=_append_worker, args=(str(path), worker, 12))
        for worker in range(4)
    ]
    for process in readers + writers:
        process.start()
    for process in writers:
        process.join(30)
        assert process.exitcode == 0
    stop.set()
    for process in readers:
        process.join(30)
        assert process.exitcode == 0
    rows = JsonlLogStore(path, max_bytes=700, max_segments=64).query(limit=1000)
    assert len(rows) == 48
    assert len({row.log_id for row in rows}) == 48


def _query_pruning_worker(path: str, stop) -> None:
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group("multiprocess-log-pruning-reader")
    store = build_jsonl_log_store(path, task_group=group, max_bytes=700, max_segments=4)
    try:
        while not stop.wait(0.001):
            rows = store.query(limit=1000)
            ids = [row.log_id for row in rows]
            if len(ids) != len(set(ids)):
                raise AssertionError("pruning JSONL query returned duplicate log identities")
            ordering = [(row.created_at, row.log_id) for row in rows]
            if ordering != sorted(ordering, reverse=True):
                raise AssertionError("pruning JSONL query returned non-deterministic order")
    finally:
        runtime.close()


def test_multiple_processes_rotate_prune_while_concurrent_readers_query(tmp_path: Path) -> None:
    import multiprocessing

    path = tmp_path / "events.jsonl"
    context = multiprocessing.get_context("spawn")
    stop = context.Event()
    readers = [
        context.Process(target=_query_pruning_worker, args=(str(path), stop))
        for _ in range(2)
    ]
    writers = [
        context.Process(target=_append_pruning_worker, args=(str(path), worker, 24))
        for worker in range(4)
    ]
    for process in readers + writers:
        process.start()
    for process in writers:
        process.join(45)
        assert process.exitcode == 0
    stop.set()
    for process in readers:
        process.join(45)
        assert process.exitcode == 0
    rows = JsonlLogStore(path, max_bytes=700, max_segments=4).query(limit=1000)
    ids = [row.log_id for row in rows]
    assert len(ids) == len(set(ids))
    ordering = [(row.created_at, row.log_id) for row in rows]
    assert ordering == sorted(ordering, reverse=True)
