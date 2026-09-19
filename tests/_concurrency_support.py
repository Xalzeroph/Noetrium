from __future__ import annotations

from pathlib import Path
from threading import Lock
from uuid import uuid4

from noetrium_platform.evidence.observability.telemetry.metric.composition import build_telemetry_sqlite_backend
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.infrastructure.reliability.forensics.composition.store import ForensicStore


_RUNTIME_LOCK = Lock()
_OWNED_RUNTIMES: list[object] = []
_OWNED_RESOURCES: list[object] = []


def _register_runtime(runtime):
    with _RUNTIME_LOCK:
        _OWNED_RUNTIMES.append(runtime)
    return runtime


def drain_test_concurrency_runtimes() -> None:
    """Close test-owned resources first, then their concurrency runtimes."""

    with _RUNTIME_LOCK:
        resources = tuple(reversed(_OWNED_RESOURCES))
        _OWNED_RESOURCES.clear()
        runtimes = tuple(reversed(_OWNED_RUNTIMES))
        _OWNED_RUNTIMES.clear()
    errors: list[BaseException] = []
    for resource in resources:
        try:
            resource.close()
        except BaseException as exc:
            errors.append(exc)
    for runtime in runtimes:
        try:
            runtime.close()
        except BaseException as exc:
            errors.append(exc)
    if errors:
        raise ExceptionGroup("test concurrency runtime shutdown failed", errors)



def owned_task_group(prefix: str = "test-concurrency"):
    runtime = _register_runtime(build_concurrency_runtime())
    return runtime.open_task_group(f"{prefix}:{uuid4().hex}")

def telemetry_backend(test_case, path: Path):
    runtime = _register_runtime(build_concurrency_runtime())
    group = runtime.open_task_group(f"test-telemetry:{uuid4().hex}")
    test_case.addCleanup(runtime.close)
    return build_telemetry_sqlite_backend(path, task_group=group)


class OwnedForensicStore(ForensicStore):
    """Test composition root that keeps production's explicit TaskGroup contract."""

    def __init__(self, root: Path, *, read_only: bool = False):
        self._test_runtime = None
        if read_only:
            super().__init__(root, read_only=True, task_group=None)
            return
        runtime = _register_runtime(build_concurrency_runtime())
        group = runtime.open_task_group(f"test-forensics:{uuid4().hex}")
        try:
            super().__init__(root, read_only=False, task_group=group)
        except BaseException:
            runtime.close()
            raise
        self._test_runtime = runtime

    def close(self) -> None:
        error = None
        try:
            super().close()
        except BaseException as exc:
            error = exc
        runtime = self._test_runtime
        self._test_runtime = None
        if runtime is not None:
            try:
                runtime.close()
            except BaseException as exc:
                if error is None:
                    error = exc
        if error is not None:
            raise error


def forensic_index(path: Path):
    from weakref import finalize
    from noetrium_platform.infrastructure.reliability.forensics.providers.index import ForensicIndex

    runtime = _register_runtime(build_concurrency_runtime())
    group = runtime.open_task_group(f"test-forensic-index:{uuid4().hex}")
    actor = group.open_serial_actor(
        f"test-forensic-index-writer:{uuid4().hex}",
        lane_id=f"test-forensic-index-writer:{uuid4().hex}",
    )
    index = ForensicIndex(path, writer_actor=actor)
    finalize(index, runtime.close)
    return index

class _InlineSerialActor:
    """Deterministic test-only actor for artifact semantics not exercising scheduling."""

    actor_id = "test-inline-serial-actor"

    def call(self, operation, fn, /, *args, **kwargs):
        del operation, kwargs
        return fn(*args)


def run_artifact_store(path: Path):
    from noetrium_platform.research.experimentation.run.runtime import DirectoryRunArtifactStore

    return DirectoryRunArtifactStore(path, writer_actor=_InlineSerialActor())


def jsonl_log_store(path: Path, *, max_bytes: int = 64 * 1024 * 1024, max_segments: int = 8):
    from noetrium_platform.evidence.observability.logging.storage.runtime.jsonl import JsonlLogStore

    return JsonlLogStore(
        path,
        writer_actor=_InlineSerialActor(),
        max_bytes=max_bytes,
        max_segments=max_segments,
    )


def server_operation_journal(path: Path):
    from noetrium_platform.infrastructure.lifecycle.server.runtime import JsonlServerOperationJournal

    return JsonlServerOperationJournal(path, writer_actor=_InlineSerialActor())


def raw_observation_lake(path: Path):
    from noetrium_platform.evidence.observability.capture.composition import build_file_raw_observation_lake

    runtime = _register_runtime(build_concurrency_runtime())
    group = runtime.open_task_group(f"test-raw-capture:{uuid4().hex}")
    lake = build_file_raw_observation_lake(path, task_group=group)
    with _RUNTIME_LOCK:
        _OWNED_RESOURCES.append(lake)
    return lake


def process_capture(path: Path, stream: str, **kwargs):
    from noetrium_platform.infrastructure.lifecycle.process.capture import SegmentedByteCapture

    runtime = _register_runtime(build_concurrency_runtime())
    group = runtime.open_task_group(f"test-process-capture:{uuid4().hex}")
    capture = SegmentedByteCapture(path, stream, task_group=group, **kwargs)
    with _RUNTIME_LOCK:
        _OWNED_RESOURCES.append(capture)
    return capture


def segmented_byte_capture(path: Path, stream: str, **kwargs):
    from noetrium_platform.infrastructure.lifecycle.process.capture import SegmentedByteCapture

    runtime = _register_runtime(build_concurrency_runtime())
    group = runtime.open_task_group(f"test-process-capture:{uuid4().hex}")
    capture = SegmentedByteCapture(path, stream, task_group=group, **kwargs)
    with _RUNTIME_LOCK:
        _OWNED_RESOURCES.append(capture)
    return capture


def make_task_group(prefix: str = "test"):
    runtime = _register_runtime(build_concurrency_runtime())
    return runtime.open_task_group(f"{prefix}:{uuid4().hex}")
