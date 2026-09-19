from __future__ import annotations

"""Machine-readable pytest evidence for the release regression runner.

The plugin is deliberately tiny and dependency-free.  It writes exactly one JSON
result outside the source tree, using temp+fsync+replace publication.  The release
runner consumes this contract instead of parsing human-oriented terminal output.
"""

from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path
import tempfile
import time

_RESULT_ENV = "RELEASE_PYTEST_RESULT_PATH"


@dataclass(frozen=True, slots=True)
class _NodeOutcome:
    passed: bool = False
    skipped: bool = False
    failed: bool = False
    xfailed: bool = False
    xpassed: bool = False


_started = time.monotonic()
_nodes: dict[str, _NodeOutcome] = {}
_collection_errors: set[str] = set()
_deselected: set[str] = set()
_file_durations: dict[str, float] = {}


def _merge(nodeid: str, **changes: bool) -> None:
    current = _nodes.get(nodeid, _NodeOutcome())
    payload = asdict(current)
    for key, value in changes.items():
        payload[key] = bool(payload[key] or value)
    _nodes[nodeid] = _NodeOutcome(**payload)


def pytest_runtest_logreport(report) -> None:  # pragma: no cover - invoked by pytest
    nodeid = str(report.nodeid)
    file_id = nodeid.split("::", 1)[0]
    _file_durations[file_id] = _file_durations.get(file_id, 0.0) + max(0.0, float(getattr(report, "duration", 0.0)))
    wasxfail = bool(getattr(report, "wasxfail", False))
    if report.failed:
        _merge(nodeid, failed=True)
        return
    if report.skipped:
        _merge(nodeid, xfailed=wasxfail, skipped=not wasxfail)
        return
    if report.when == "call" and report.passed:
        _merge(nodeid, xpassed=wasxfail, passed=not wasxfail)


def pytest_collectreport(report) -> None:  # pragma: no cover - invoked by pytest
    if report.failed:
        _collection_errors.add(str(report.nodeid or report.fspath))


def pytest_deselected(items) -> None:  # pragma: no cover - invoked by pytest
    for item in items:
        _deselected.add(str(item.nodeid))


def _final_counts() -> dict[str, int]:
    # Precedence matters: teardown failure must not also count as a pass.
    passed = skipped = failed = xfailed = xpassed = 0
    for outcome in _nodes.values():
        if outcome.failed:
            failed += 1
        elif outcome.xpassed:
            xpassed += 1
        elif outcome.xfailed:
            xfailed += 1
        elif outcome.skipped:
            skipped += 1
        elif outcome.passed:
            passed += 1
    return {
        "passed": passed,
        "skipped": skipped,
        "failed": failed,
        "xfailed": xfailed,
        "xpassed": xpassed,
    }


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        if os.name != "nt":
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def pytest_sessionfinish(session, exitstatus) -> None:  # pragma: no cover - invoked by pytest
    result_path = os.environ.get(_RESULT_ENV)
    if not result_path:
        return
    counts = _final_counts()
    payload = {
        "schema_version": 1,
        "tests_collected": int(getattr(session, "testscollected", 0)),
        "passed": counts["passed"],
        "skipped": counts["skipped"],
        "failed": counts["failed"],
        "xfailed": counts["xfailed"],
        "xpassed": counts["xpassed"],
        "collection_errors": len(_collection_errors),
        "deselected": len(_deselected),
        "pytest_exitstatus": int(exitstatus),
        "duration_seconds": max(0.0, time.monotonic() - _started),
        "file_durations_seconds": {key: _file_durations[key] for key in sorted(_file_durations)},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    _atomic_write(Path(result_path), raw)
