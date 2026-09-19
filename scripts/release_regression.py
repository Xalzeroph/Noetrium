from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import heapq
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.research.execution.admission.api import AdmissionBudget

from noetrium_platform.foundation.governance.release.runtime.regression_state import (
    REGRESSION_STATE_SCHEMA_VERSION,
    ReleaseRegressionShardPlan,
    ReleaseRegressionShardResult,
    ReleaseRegressionState,
    default_regression_state_path,
    load_regression_state,
    shard_identity_digest,
    test_inventory_digest,
    write_regression_state,
)
from noetrium_platform.foundation.governance.release.runtime.regression_timing import (
    default_timing_history_path,
    load_timing_history,
    write_timing_history,
)
from scripts.test_system import TestSystemError, check as check_test_system
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskContextPort,
    TaskGroupPort,
)
from noetrium_platform.composition.concurrency import build_execution_concurrency_runtime


# Kept only for backwards-compatible diagnostics/tests.  Release evidence no
# longer depends on human terminal output parsing.
_COLLECT_RE = re.compile(r"(?P<count>\d+) tests? collected")
_RESULT_RE = re.compile(r"(?P<passed>\d+) passed(?:, (?P<skipped>\d+) skipped)?")
_IS_WINDOWS = os.name == "nt"
_RESULT_SCHEMA_VERSION = 1
_PARALLEL_SHARD_SIZE = 8
_DEFAULT_MAX_PARALLEL_WORKERS = 4
_EXCLUSIVE_SHARD_TARGET_SECONDS = 20.0


def _parallel_worker_limit() -> int:
    raw = os.environ.get("RELEASE_MAX_PARALLEL_WORKERS", "").strip()
    if raw:
        try:
            configured = max(1, int(raw))
        except ValueError as exc:
            raise ReleaseRegressionFailure("RELEASE_MAX_PARALLEL_WORKERS must be a positive integer") from exc
    else:
        configured = _DEFAULT_MAX_PARALLEL_WORKERS
    cpu = max(1, int(os.cpu_count() or 1))
    return max(1, min(configured, cpu))



class ReleaseRegressionFailure(RuntimeError):
    pass

_ACTIVE_PROCESS_GROUPS: set[int] = set()
_ACTIVE_PROCESS_GROUPS_LOCK = threading.RLock()


def _register_process_group(pgid: int) -> None:
    with _ACTIVE_PROCESS_GROUPS_LOCK:
        _ACTIVE_PROCESS_GROUPS.add(int(pgid))


def _unregister_process_group(pgid: int) -> None:
    with _ACTIVE_PROCESS_GROUPS_LOCK:
        _ACTIVE_PROCESS_GROUPS.discard(int(pgid))


def _active_process_groups_snapshot() -> tuple[int, ...]:
    with _ACTIVE_PROCESS_GROUPS_LOCK:
        return tuple(sorted(_ACTIVE_PROCESS_GROUPS))



@dataclass(frozen=True, slots=True)
class ReleaseRegressionResult:
    collected: int
    passed: int
    skipped: int
    shard_count: int
    test_inventory_sha256: str
    runtime_sha256: str
    plan_sha256: str


@dataclass(frozen=True, slots=True)
class _PytestShardEvidence:
    schema_version: int
    tests_collected: int
    passed: int
    skipped: int
    failed: int
    xfailed: int
    xpassed: int
    collection_errors: int
    deselected: int
    pytest_exitstatus: int
    duration_seconds: float
    file_durations_seconds: dict[str, float] = field(default_factory=dict)

    def validate_release_clean(self) -> None:
        if self.schema_version != _RESULT_SCHEMA_VERSION:
            raise ReleaseRegressionFailure("pytest release-result schema mismatch")
        counters = (
            self.tests_collected,
            self.passed,
            self.skipped,
            self.failed,
            self.xfailed,
            self.xpassed,
            self.collection_errors,
            self.deselected,
        )
        if any(value < 0 for value in counters):
            raise ReleaseRegressionFailure("pytest release-result contains negative counters")
        if any(float(value) < 0 for value in self.file_durations_seconds.values()):
            raise ReleaseRegressionFailure("pytest release-result contains negative file duration")
        if self.pytest_exitstatus != 0:
            raise ReleaseRegressionFailure(f"pytest release-result exit status {self.pytest_exitstatus}")
        if self.failed or self.collection_errors or self.xfailed or self.xpassed or self.deselected:
            raise ReleaseRegressionFailure(
                "release shard is not clean: "
                f"failed={self.failed} collection_errors={self.collection_errors} "
                f"xfailed={self.xfailed} xpassed={self.xpassed} deselected={self.deselected}"
            )
        if self.tests_collected <= 0:
            raise ReleaseRegressionFailure("release shard collected no tests")
        if self.passed + self.skipped != self.tests_collected:
            raise ReleaseRegressionFailure(
                "release shard inventory mismatch: "
                f"collected={self.tests_collected} passed={self.passed} skipped={self.skipped}"
            )


def _signal_process_group(pgid: int, sig: signal.Signals) -> bool:
    if _IS_WINDOWS:
        if sig is signal.SIGTERM:
            try:
                os.kill(pgid, signal.CTRL_BREAK_EVENT)
                return True
            except (AttributeError, OSError):
                return _process_group_exists(pgid)
        result = subprocess.run(
            ["taskkill", "/PID", str(pgid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return False
    return True


def _process_group_exists(pgid: int) -> bool:
    if _IS_WINDOWS:
        try:
            os.kill(pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _force_process_group(pgid: int) -> bool:
    if _IS_WINDOWS:
        result = subprocess.run(
            ["taskkill", "/PID", str(pgid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0
    return _signal_process_group(pgid, signal.SIGKILL)


def _reap_process_group(pgid: int, *, grace_seconds: float = 0.25) -> None:
    if not _signal_process_group(pgid, signal.SIGTERM):
        return
    deadline = time.monotonic() + max(0.0, grace_seconds)
    while time.monotonic() < deadline:
        if not _process_group_exists(pgid):
            return
        time.sleep(0.01)
    _force_process_group(pgid)
    if not _IS_WINDOWS:
        try:
            os.waitpid(pgid, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass


@contextmanager
def _child_process_group_signal_guard(pgid: int):
    """Install per-call signal cleanup only when invoked on the main thread."""

    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous: dict[signal.Signals, object] = {}

    def handle(signum: int, _frame) -> None:
        _reap_process_group(pgid)
        raise SystemExit(128 + int(signum))

    signals = [signal.SIGTERM, signal.SIGINT]
    if _IS_WINDOWS and hasattr(signal, "SIGBREAK"):
        signals.append(signal.SIGBREAK)
    for sig in signals:
        previous[sig] = signal.getsignal(sig)
        signal.signal(sig, handle)
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


@contextmanager
def _active_process_groups_signal_guard():
    """Main-runner signal guard that reaps every concurrently active shard."""

    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous: dict[signal.Signals, object] = {}

    def handle(signum: int, _frame) -> None:
        for pgid in _active_process_groups_snapshot():
            _reap_process_group(pgid)
        raise SystemExit(128 + int(signum))

    signals = [signal.SIGTERM, signal.SIGINT]
    if _IS_WINDOWS and hasattr(signal, "SIGBREAK"):
        signals.append(signal.SIGBREAK)
    for sig in signals:
        previous[sig] = signal.getsignal(sig)
        signal.signal(sig, handle)
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _decode_diagnostic_output(payload: bytes) -> str:
    """Decode human-only subprocess diagnostics without weakening release evidence."""

    return payload.decode("utf-8", errors="replace")


def _write_diagnostic_output(output: str, *, stream=None) -> None:
    """Write human diagnostics without letting a narrow console codec abort release work."""

    target = sys.stdout if stream is None else stream
    encoding = getattr(target, "encoding", None)
    safe = output if not encoding else output.encode(encoding, errors="backslashreplace").decode(encoding)
    target.write(safe)
    target.flush()


def _run_pytest(
    root: Path,
    args: list[str],
    *,
    timeout_seconds: float = 180.0,
    echo_success: bool = False,
    result_path: Path | None = None,
) -> str:
    """Run one pytest shard in a private process group.

    stdout goes to a regular file so leaked descendants cannot retain a pipe and
    deadlock the runner.  When ``result_path`` is supplied, the worker injects the
    machine-readable release plugin; human output remains diagnostics only.
    """

    with (
        tempfile.NamedTemporaryFile(mode="w+b", suffix=".pytest.log") as log,
        tempfile.TemporaryDirectory(prefix="release-pycache-") as pycache_root,
    ):
        worker = Path(__file__).resolve().with_name("release_pytest_worker.py")
        if not worker.is_file():
            raise ReleaseRegressionFailure("release pytest worker is missing")
        env = os.environ.copy()
        env["PYTHONPYCACHEPREFIX"] = pycache_root
        if result_path is not None:
            env["RELEASE_PYTEST_RESULT_PATH"] = str(Path(result_path).resolve())
        process = subprocess.Popen(
            [sys.executable, str(worker), *args],
            cwd=root,
            text=False,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=not _IS_WINDOWS,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if _IS_WINDOWS else 0,
        )
        pgid = process.pid
        _register_process_group(pgid)
        try:
            with _child_process_group_signal_guard(pgid):
                returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            _reap_process_group(pgid)
            leader_reaped = True
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    leader_reaped = False
            log.flush(); log.seek(0); output = _decode_diagnostic_output(log.read()); _write_diagnostic_output(output)
            suffix = "" if leader_reaped else f"; pytest leader pid={process.pid} remained unreaped after SIGKILL"
            raise ReleaseRegressionFailure(
                f"pytest timed out after {timeout_seconds:g}s: {' '.join(args)}{suffix}"
            ) from exc
        else:
            _reap_process_group(pgid)
        finally:
            _unregister_process_group(pgid)
        log.flush(); log.seek(0); output = _decode_diagnostic_output(log.read())
    if returncode != 0:
        _write_diagnostic_output(output)
        raise ReleaseRegressionFailure(f"pytest failed with exit code {returncode}")
    if echo_success:
        _write_diagnostic_output(output)
    return output


def _decode_pytest_shard_evidence(path: Path) -> _PytestShardEvidence:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("pytest release-result must be an object")
        result = _PytestShardEvidence(**payload)
        result.validate_release_clean()
        return result
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        if isinstance(exc, ReleaseRegressionFailure):
            raise
        raise ReleaseRegressionFailure("pytest release-result is missing or corrupt") from exc


def _run_pytest_shard(
    root: Path,
    args: list[str],
    *,
    timeout_seconds: float = 180.0,
) -> _PytestShardEvidence:
    with tempfile.TemporaryDirectory(prefix="release-pytest-result-") as td:
        shard_temp_root = Path(td)
        result_path = shard_temp_root / "result.json"
        basetemp = shard_temp_root / "pytest"
        _run_pytest(
            root,
            ["--basetemp", str(basetemp), *args],
            timeout_seconds=timeout_seconds,
            result_path=result_path,
        )
        return _decode_pytest_shard_evidence(result_path)


def _parse_collected(output: str) -> int:
    matches = list(_COLLECT_RE.finditer(output))
    if not matches:
        raise ReleaseRegressionFailure("unable to parse pytest collection count")
    return int(matches[-1].group("count"))


def _parse_result(output: str) -> tuple[int, int]:
    matches = list(_RESULT_RE.finditer(output))
    if not matches:
        raise ReleaseRegressionFailure("unable to parse pytest shard result")
    match = matches[-1]
    return int(match.group("passed")), int(match.group("skipped") or 0)


def _pytest_plugin_versions() -> tuple[tuple[str, str], ...]:
    rows: set[tuple[str, str]] = set()
    try:
        entries = importlib.metadata.entry_points(group="pytest11")
    except TypeError:  # Python/importlib compatibility
        entries = importlib.metadata.entry_points().select(group="pytest11")
    for entry in entries:
        dist = getattr(entry, "dist", None)
        name = str(getattr(dist, "name", "") or entry.module.split(".", 1)[0]).lower()
        try:
            version = str(getattr(dist, "version", "") or importlib.metadata.version(name))
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        rows.add((name, version))
    return tuple(sorted(rows))


def _regression_runtime_digest() -> str:
    try:
        import pytest
        pytest_version = pytest.__version__
    except ModuleNotFoundError:
        pytest_version = "unavailable"
    payload = {
        "python_version": sys.version,
        "python_implementation": sys.implementation.name,
        "python_cache_tag": sys.implementation.cache_tag,
        "pytest_version": pytest_version,
        "pytest_plugins": _pytest_plugin_versions(),
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "platform_machine": platform.machine(),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _release_test_inventory(root: Path) -> tuple[tuple[Path, str], ...]:
    test_system_path = root / "tests" / "TEST_SYSTEM.json"
    if test_system_path.is_file():
        try:
            classified = check_test_system(root)
        except TestSystemError as exc:
            raise ReleaseRegressionFailure(f"test system inventory is invalid: {exc}") from exc
        print(f"RELEASE_TEST_SYSTEM_CHECK_PASS files={len(classified)}", flush=True)
        rows = tuple((root / row.path, row.parallelism) for row in classified)
    else:
        rows = tuple((path, "exclusive") for path in sorted((root / "tests").glob("test_*.py")))
    if not rows:
        raise ReleaseRegressionFailure("release regression has no test files")
    missing = tuple(path for path, _parallelism in rows if not path.is_file())
    if missing:
        raise ReleaseRegressionFailure(f"release test inventory contains missing file: {missing[0]}")
    return tuple(sorted(rows, key=lambda item: item[0]))


def _release_test_files(root: Path) -> tuple[Path, ...]:
    return tuple(path for path, _parallelism in _release_test_inventory(root))


@dataclass(frozen=True, slots=True)
class _ShardPlan:
    shard_index: int
    files: tuple[Path, ...]
    isolation_class: str

    @property
    def parallel_safe(self) -> bool:
        return self.isolation_class != "exclusive"


def _balanced_parallel_groups(
    root: Path,
    files: tuple[Path, ...],
    *,
    timing_history,
) -> tuple[tuple[Path, ...], ...]:
    """LPT-balance one isolation class while preserving complete coverage.

    Timing history is advisory and may affect the *initial* grouping only.  The
    resulting plan is immediately frozen in durable regression state and its
    digest is carried into release evidence.  Resume therefore never depends on
    mutable timing history.
    """

    if not files:
        return ()
    shard_count = max(1, (len(files) + _PARALLEL_SHARD_SIZE - 1) // _PARALLEL_SHARD_SIZE)
    max_files = (len(files) + shard_count - 1) // shard_count
    buckets: list[list[Path]] = [[] for _ in range(shard_count)]
    queue = [(0.0, index) for index in range(shard_count)]
    heapq.heapify(queue)
    ranked = sorted(
        files,
        key=lambda path: (
            -timing_history.estimate((path.relative_to(root).as_posix(),)),
            path.as_posix(),
        ),
    )
    for path in ranked:
        load, index = heapq.heappop(queue)
        buckets[index].append(path)
        estimate = timing_history.estimate((path.relative_to(root).as_posix(),))
        if len(buckets[index]) < max_files:
            heapq.heappush(queue, (load + estimate, index))
    return tuple(tuple(sorted(bucket)) for bucket in buckets if bucket)


def _bounded_exclusive_groups(
    root: Path,
    files: tuple[Path, ...],
    *,
    shard_size: int,
    timing_history,
    target_seconds: float = _EXCLUSIVE_SHARD_TARGET_SECONDS,
) -> tuple[tuple[Path, ...], ...]:
    """Split exclusive work by both file count and advisory wall-time history.

    Exclusive tests must retain lexical execution order, so unlike parallel-safe
    tests they are not LPT-reordered.  Timing history only chooses deterministic
    cut points for a newly-created plan; the resulting groups are frozen in the
    durable plan digest before execution.  A single file whose estimate exceeds
    the target is allowed to form an oversized one-file shard.
    """

    if shard_size <= 0:
        raise ValueError("exclusive shard size must be positive")
    if target_seconds <= 0:
        raise ValueError("exclusive shard target must be positive")
    groups: list[tuple[Path, ...]] = []
    current: list[Path] = []
    current_seconds = 0.0
    for path in files:
        estimate = timing_history.estimate((path.relative_to(root).as_posix(),))
        would_exceed_time = bool(current) and current_seconds + estimate > target_seconds
        would_exceed_count = len(current) >= shard_size
        if would_exceed_time or would_exceed_count:
            groups.append(tuple(current))
            current = []
            current_seconds = 0.0
        current.append(path)
        current_seconds += estimate
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _build_shard_plan(
    root: Path,
    *,
    shard_size: int,
    inventory: tuple[tuple[Path, str], ...],
    timing_history,
) -> tuple[_ShardPlan, ...]:
    plans: list[_ShardPlan] = []
    index = 1
    for isolation_class in ("parallel-safe", "process-isolated"):
        files = tuple(path for path, isolation in inventory if isolation == isolation_class)
        for group in _balanced_parallel_groups(root, files, timing_history=timing_history):
            plans.append(_ShardPlan(index, group, isolation_class))
            index += 1
    exclusive = tuple(path for path, isolation in inventory if isolation == "exclusive")
    for group in _bounded_exclusive_groups(
        root,
        exclusive,
        shard_size=shard_size,
        timing_history=timing_history,
    ):
        plans.append(_ShardPlan(index, group, "exclusive"))
        index += 1
    return tuple(plans)


def _persisted_plan(root: Path, state: ReleaseRegressionState) -> tuple[_ShardPlan, ...]:
    return tuple(
        _ShardPlan(
            item.shard_index,
            tuple(root / relative for relative in item.relative_test_files),
            item.isolation_class,
        )
        for item in state.planned_shards
    )


def _state_with_plan(root: Path, state: ReleaseRegressionState, plan: tuple[_ShardPlan, ...]) -> ReleaseRegressionState:
    persisted = tuple(
        ReleaseRegressionShardPlan(
            shard_index=item.shard_index,
            relative_test_files=tuple(path.relative_to(root).as_posix() for path in item.files),
            isolation_class=item.isolation_class,
        )
        for item in plan
    )
    return state.with_plan(persisted)


def _validate_plan_against_inventory(
    root: Path,
    plan: tuple[_ShardPlan, ...],
    inventory: tuple[tuple[Path, str], ...],
) -> None:
    expected = {path.relative_to(root).as_posix(): isolation for path, isolation in inventory}
    observed: dict[str, str] = {}
    indexes: set[int] = set()
    for shard in plan:
        if shard.shard_index in indexes:
            raise ReleaseRegressionFailure("release regression plan contains duplicate shard index")
        indexes.add(shard.shard_index)
        for path in shard.files:
            relative = path.relative_to(root).as_posix()
            if relative in observed:
                raise ReleaseRegressionFailure(f"release regression plan duplicates test file: {relative}")
            observed[relative] = shard.isolation_class
    missing = sorted(set(expected) - set(observed))
    extra = sorted(set(observed) - set(expected))
    if missing:
        raise ReleaseRegressionFailure(f"release regression plan omits test file: {missing[0]}")
    if extra:
        raise ReleaseRegressionFailure(f"release regression plan contains unknown test file: {extra[0]}")
    for relative, isolation in expected.items():
        if observed[relative] != isolation:
            raise ReleaseRegressionFailure(
                f"release regression plan isolation drift: {relative}: "
                f"planned={observed[relative]} expected={isolation}"
            )




def _parallel_worker_count(plan_count: int) -> int:
    """Compatibility/testing wrapper around the adaptive worker budget."""
    if plan_count <= 0:
        return 0
    return min(int(plan_count), _parallel_worker_limit())

def _execute_plan_shard(root: Path, plan: _ShardPlan) -> tuple[ReleaseRegressionShardResult, dict[str, float]]:
    relative = tuple(path.relative_to(root).as_posix() for path in plan.files)
    print(
        f"RELEASE_TEST_SHARD_START {plan.shard_index} files={relative[0]}..{relative[-1]} "
        f"isolation={plan.isolation_class} parallel_safe={str(plan.parallel_safe).lower()}",
        flush=True,
    )
    shard_evidence = _run_pytest_shard(root, ["-q", *relative])
    result = ReleaseRegressionShardResult(
        shard_index=plan.shard_index,
        shard_identity_sha256=shard_identity_digest(relative),
        first_test_file=relative[0],
        last_test_file=relative[-1],
        collected=shard_evidence.tests_collected,
        passed=shard_evidence.passed,
        skipped=shard_evidence.skipped,
        duration_seconds=shard_evidence.duration_seconds,
    )
    return result, dict(shard_evidence.file_durations_seconds)



def _partition_pending_plans(
    root: Path,
    plan: tuple[_ShardPlan, ...],
    state: ReleaseRegressionState,
) -> tuple[dict[int, ReleaseRegressionShardResult], list[_ShardPlan], list[_ShardPlan]]:
    results: dict[int, ReleaseRegressionShardResult] = {}
    pending_parallel: list[_ShardPlan] = []
    pending_exclusive: list[_ShardPlan] = []
    cached_by_identity = {
        (row.shard_index, row.shard_identity_sha256): row for row in state.completed_shards
    }
    for item in plan:
        relative = tuple(path.relative_to(root).as_posix() for path in item.files)
        cached = cached_by_identity.get((item.shard_index, shard_identity_digest(relative)))
        if cached is not None:
            print(
                f"RELEASE_TEST_SHARD_RESUME {item.shard_index} collected={cached.collected} "
                f"passed={cached.passed} skipped={cached.skipped}",
                flush=True,
            )
            results[item.shard_index] = cached
        elif item.parallel_safe:
            pending_parallel.append(item)
        else:
            pending_exclusive.append(item)
    return results, pending_parallel, pending_exclusive


def _persist_completed_shard(
    *,
    state_path: Path,
    timing_path: Path,
    state: ReleaseRegressionState,
    timing_history,
    result: ReleaseRegressionShardResult,
    observations: dict[str, float],
) -> tuple[ReleaseRegressionState, object]:
    # Regression state is evidence-critical and is fsync-published after every
    # shard. Timing history is advisory only, so buffer it in memory and flush
    # once per execution phase to avoid a second durable write per shard.
    timing_history = timing_history.with_observations(observations)
    state = state.with_result(result)
    write_regression_state(state_path, state)
    print(
        f"RELEASE_TEST_SHARD_PASS {result.shard_index} collected={result.collected} "
        f"passed={result.passed} skipped={result.skipped} duration={result.duration_seconds:.3f}s",
        flush=True,
    )
    return state, timing_history


def _estimated_plan_seconds(root: Path, timing_history, item: _ShardPlan) -> float:
    relative = tuple(path.relative_to(root).as_posix() for path in item.files)
    return timing_history.estimate(relative)


def _run_parallel_plans(
    root: Path,
    plans: list[_ShardPlan],
    *,
    state_path: Path,
    timing_path: Path,
    state: ReleaseRegressionState,
    timing_history,
    results: dict[int, ReleaseRegressionShardResult],
    task_group: TaskGroupPort | None = None,
) -> tuple[ReleaseRegressionState, object]:
    """Run parallel-safe shards through a bounded rolling window.

    Backpressure is part of release correctness: completed shards are persisted
    before new work is admitted, so a saturated executor cannot leave durable
    progress at zero merely because the producer is still trying to submit the
    remainder of the plan.

    Algorithm-Complexity: O(N)
    Algorithm-Rationale: Every shard is submitted once, removed from the active window once, and persisted once; the active window is bounded by the fixed worker count.
    Concurrency-Policy: BOUNDED_TASK_FANOUT
    Concurrency-Rationale: The producer admits at most ``workers`` active shard handles and only replenishes that fixed window after completed handles are durably persisted.
    """

    if not plans:
        return state, timing_history
    plans.sort(key=lambda item: (-_estimated_plan_seconds(root, timing_history, item), item.shard_index))
    workers = _parallel_worker_count(len(plans))
    print(f"RELEASE_TEST_PARALLEL_START shards={len(plans)} workers={workers}", flush=True)
    owned_runtime = None
    resolved_group = task_group
    if resolved_group is None:
        total_admission = max(workers, len(plans))
        owned_runtime = build_execution_concurrency_runtime(
            concurrency_budget=ConcurrencyBudget(
                max_blocking_io_workers=workers,
                max_cpu_workers=1,
                max_blocking_io_in_flight=workers,
                default_queue_capacity=max(16, len(plans)),
            ),
            admission_budget=AdmissionBudget(
                max_blocking_io_in_flight=workers,
            ),
            blocking_io_thread_name_prefix="release-pytest-shard",
            timer_name="release-regression-timer",
        )
        resolved_group = owned_runtime.open_task_group("release-regression", tenant_id="release", resource_id="regression")

    invocation_id = f"{state.plan_sha256[:12]}:{time.monotonic_ns()}"

    def execute_shard(
        context: TaskContextPort,
        shard_root: Path,
        shard_plan: _ShardPlan,
    ):
        context.checkpoint()
        value = _execute_plan_shard(shard_root, shard_plan)
        context.checkpoint()
        return value

    pending = deque(plans)
    active: list[tuple[_ShardPlan, object]] = []
    try:
        while pending or active:
            while pending and len(active) < workers:
                item = pending.popleft()
                handle = resolved_group.submit(
                    ExecutionSpec(
                        task_id=f"release-regression-shard:{invocation_id}:{item.shard_index}",
                        lane_kind=ExecutionLaneKind.BLOCKING_IO,
                    ),
                    execute_shard,
                    root,
                    item,
                    deadline=Deadline.after(3600.0),
                )
                active.append((item, handle))

            completed = [(item, handle) for item, handle in active if handle.done()]
            if not completed:
                time.sleep(0.01)
                continue

            completed_ids = {id(handle) for _item, handle in completed}
            for _item, handle in sorted(completed, key=lambda row: row[0].shard_index):
                result, observations = handle.result(timeout=0)
                state, timing_history = _persist_completed_shard(
                    state_path=state_path,
                    timing_path=timing_path,
                    state=state,
                    timing_history=timing_history,
                    result=result,
                    observations=observations,
                )
                results[result.shard_index] = result
            active = [(item, handle) for item, handle in active if id(handle) not in completed_ids]
    finally:
        if owned_runtime is not None:
            owned_runtime.close()
    return state, timing_history


def _run_exclusive_plans(
    root: Path,
    plans: list[_ShardPlan],
    *,
    state_path: Path,
    timing_path: Path,
    state: ReleaseRegressionState,
    timing_history,
    results: dict[int, ReleaseRegressionShardResult],
) -> tuple[ReleaseRegressionState, object]:
    for item in plans:
        result, observations = _execute_plan_shard(root, item)
        state, timing_history = _persist_completed_shard(
            state_path=state_path,
            timing_path=timing_path,
            state=state,
            timing_history=timing_history,
            result=result,
            observations=observations,
        )
        results[result.shard_index] = result
    return state, timing_history


def _summarize_regression_results(
    results: dict[int, ReleaseRegressionShardResult],
    *,
    inventory_sha256: str,
    runtime_sha256: str,
    plan_sha256: str,
) -> ReleaseRegressionResult:
    ordered = tuple(results[index] for index in sorted(results))
    collected = sum(item.collected for item in ordered)
    passed = sum(item.passed for item in ordered)
    skipped = sum(item.skipped for item in ordered)
    if collected <= 0 or passed + skipped != collected:
        raise ReleaseRegressionFailure(
            "release regression inventory mismatch: "
            f"collected={collected} passed={passed} skipped={skipped}"
        )
    print(f"RELEASE_TEST_EXECUTION_INVENTORY_PASS collected={collected}", flush=True)
    return ReleaseRegressionResult(
        collected=collected,
        passed=passed,
        skipped=skipped,
        shard_count=len(ordered),
        test_inventory_sha256=inventory_sha256,
        runtime_sha256=runtime_sha256,
        plan_sha256=plan_sha256,
    )


def run_release_regression(
    root: Path,
    *,
    source_manifest_digest: str,
    shard_size: int = 32,
    state_path: Path | None = None,
    task_group: TaskGroupPort | None = None,
) -> ReleaseRegressionResult:
    """Run/resume the complete release inventory with durable exact checkpoints."""

    root = Path(root).resolve()
    if shard_size <= 0:
        raise ValueError("shard_size must be positive")
    if len(source_manifest_digest) != 64:
        raise ValueError("source_manifest_digest must be SHA-256")

    inventory = _release_test_inventory(root)
    relative_files = tuple(path.relative_to(root).as_posix() for path, _parallelism in inventory)
    inventory_sha256 = test_inventory_digest(relative_files)
    runtime_sha256 = _regression_runtime_digest()
    resolved_state_path = Path(state_path) if state_path is not None else default_regression_state_path(root)
    timing_path = default_timing_history_path(root)
    timing_history = load_timing_history(timing_path)

    try:
        state = load_regression_state(resolved_state_path)
    except ValueError as exc:
        raise ReleaseRegressionFailure("release regression durable state is corrupt") from exc

    if state is None or not state.matches(
        source_manifest_digest=source_manifest_digest,
        test_inventory_sha256=inventory_sha256,
        runtime_sha256=runtime_sha256,
        shard_size=shard_size,
    ):
        state = ReleaseRegressionState(
            schema_version=REGRESSION_STATE_SCHEMA_VERSION,
            source_manifest_digest=source_manifest_digest,
            test_inventory_sha256=inventory_sha256,
            runtime_sha256=runtime_sha256,
            shard_size=shard_size,
            planned_shards=(),
            completed_shards=(),
        )
        write_regression_state(resolved_state_path, state)
        print("RELEASE_TEST_STATE_INITIALIZED", flush=True)
    else:
        print(f"RELEASE_TEST_STATE_RESUME completed_shards={len(state.completed_shards)}", flush=True)

    if state.planned_shards:
        plan = _persisted_plan(root, state)
    else:
        plan = _build_shard_plan(
            root,
            shard_size=shard_size,
            inventory=inventory,
            timing_history=timing_history,
        )
        state = _state_with_plan(root, state, plan)
        write_regression_state(resolved_state_path, state)
        print(f"RELEASE_TEST_PLAN_FROZEN shards={len(plan)}", flush=True)

    _validate_plan_against_inventory(root, plan, inventory)
    print(f"RELEASE_TEST_PLAN_VERIFY_PASS sha256={state.plan_sha256}", flush=True)
    results, pending_parallel, pending_exclusive = _partition_pending_plans(root, plan, state)
    with _active_process_groups_signal_guard():
        state, timing_history = _run_parallel_plans(
            root,
            pending_parallel,
            state_path=resolved_state_path,
            timing_path=timing_path,
            state=state,
            timing_history=timing_history,
            results=results,
            task_group=task_group,
        )
        if pending_parallel:
            write_timing_history(timing_path, timing_history)
        state, timing_history = _run_exclusive_plans(
            root,
            pending_exclusive,
            state_path=resolved_state_path,
            timing_path=timing_path,
            state=state,
            timing_history=timing_history,
            results=results,
        )
        if pending_exclusive:
            write_timing_history(timing_path, timing_history)
    return _summarize_regression_results(
        results,
        inventory_sha256=inventory_sha256,
        runtime_sha256=runtime_sha256,
        plan_sha256=state.plan_sha256,
    )


__all__ = [
    "ReleaseRegressionFailure",
    "ReleaseRegressionResult",
    "run_release_regression",
]
