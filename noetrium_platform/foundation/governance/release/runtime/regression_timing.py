from __future__ import annotations

"""Advisory timing history for release-regression scheduling.

Timing data is deliberately *not* release evidence.  It may change execution
order, but never test selection, shard identity, pass/fail accounting, or cache
validity.  Corrupt/missing history therefore degrades safely to deterministic
lexical scheduling instead of blocking or weakening a release.
"""

from dataclasses import dataclass
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes


TIMING_HISTORY_SCHEMA_VERSION = 1
_DEFAULT_ESTIMATE_SECONDS = 1.0
_EWMA_ALPHA = 0.35


@dataclass(frozen=True, slots=True)
class FileTiming:
    ewma_seconds: float
    samples: int

    def __post_init__(self) -> None:
        if self.ewma_seconds < 0 or self.samples <= 0:
            raise ValueError("invalid release timing sample")


@dataclass(frozen=True, slots=True)
class ReleaseRegressionTimingHistory:
    schema_version: int
    files: dict[str, FileTiming]

    @classmethod
    def empty(cls) -> "ReleaseRegressionTimingHistory":
        return cls(TIMING_HISTORY_SCHEMA_VERSION, {})

    def estimate(self, relative_files: tuple[str, ...]) -> float:
        return sum(
            self.files.get(path, FileTiming(_DEFAULT_ESTIMATE_SECONDS, 1)).ewma_seconds
            for path in relative_files
        )

    def with_observations(self, observations: dict[str, float]) -> "ReleaseRegressionTimingHistory":
        updated = dict(self.files)
        for path, raw_seconds in observations.items():
            seconds = max(0.0, float(raw_seconds))
            current = updated.get(path)
            if current is None:
                updated[path] = FileTiming(seconds, 1)
            else:
                updated[path] = FileTiming(
                    current.ewma_seconds * (1.0 - _EWMA_ALPHA) + seconds * _EWMA_ALPHA,
                    current.samples + 1,
                )
        return ReleaseRegressionTimingHistory(TIMING_HISTORY_SCHEMA_VERSION, updated)

    def to_json_bytes(self) -> bytes:
        payload = {
            "schema_version": self.schema_version,
            "files": {
                path: {"ewma_seconds": value.ewma_seconds, "samples": value.samples}
                for path, value in sorted(self.files.items())
            },
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def default_timing_history_path(root: Path) -> Path:
    resolved = Path(root).resolve()
    return resolved.parent / f".{resolved.name}.release-regression-timings.json"


def load_timing_history(path: Path) -> ReleaseRegressionTimingHistory:
    path = Path(path)
    if not path.is_file():
        return ReleaseRegressionTimingHistory.empty()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or int(payload.get("schema_version", 0)) != TIMING_HISTORY_SCHEMA_VERSION:
            return ReleaseRegressionTimingHistory.empty()
        raw_files = payload.get("files", {})
        if not isinstance(raw_files, dict):
            return ReleaseRegressionTimingHistory.empty()
        files: dict[str, FileTiming] = {}
        for name, raw in raw_files.items():
            if not isinstance(name, str) or not isinstance(raw, dict):
                return ReleaseRegressionTimingHistory.empty()
            files[name] = FileTiming(float(raw["ewma_seconds"]), int(raw["samples"]))
        return ReleaseRegressionTimingHistory(TIMING_HISTORY_SCHEMA_VERSION, files)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return ReleaseRegressionTimingHistory.empty()


def write_timing_history(path: Path, history: ReleaseRegressionTimingHistory) -> None:
    atomic_replace_bytes(Path(path), history.to_json_bytes())


__all__ = [
    "FileTiming",
    "ReleaseRegressionTimingHistory",
    "TIMING_HISTORY_SCHEMA_VERSION",
    "default_timing_history_path",
    "load_timing_history",
    "write_timing_history",
]
