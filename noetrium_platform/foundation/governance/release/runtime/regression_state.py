from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes, durable_unlink


REGRESSION_STATE_SCHEMA_VERSION = 4
_ALLOWED_ISOLATION_CLASSES = frozenset({"parallel-safe", "process-isolated", "exclusive"})


@dataclass(frozen=True, slots=True)
class ReleaseRegressionShardPlan:
    shard_index: int
    relative_test_files: tuple[str, ...]
    isolation_class: str

    def __post_init__(self) -> None:
        if self.shard_index <= 0:
            raise ValueError("release regression shard index must be positive")
        if not self.relative_test_files:
            raise ValueError("release regression shard plan cannot be empty")
        if len(set(self.relative_test_files)) != len(self.relative_test_files):
            raise ValueError("release regression shard plan contains duplicate files")
        if self.isolation_class not in _ALLOWED_ISOLATION_CLASSES:
            raise ValueError(f"unsupported release shard isolation class: {self.isolation_class}")

    @property
    def parallel_safe(self) -> bool:
        return self.isolation_class != "exclusive"

    @property
    def identity_sha256(self) -> str:
        return shard_identity_digest(self.relative_test_files)


@dataclass(frozen=True, slots=True)
class ReleaseRegressionShardResult:
    shard_index: int
    shard_identity_sha256: str
    first_test_file: str
    last_test_file: str
    collected: int
    passed: int
    skipped: int
    duration_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.shard_index <= 0:
            raise ValueError("release regression shard index must be positive")
        if len(self.shard_identity_sha256) != 64:
            raise ValueError("release regression shard identity must be SHA-256")
        if self.collected < 0 or self.passed < 0 or self.skipped < 0:
            raise ValueError("release regression counters cannot be negative")
        if self.passed + self.skipped != self.collected:
            raise ValueError("release regression shard must account for every collected test")
        if self.duration_seconds < 0:
            raise ValueError("release regression duration cannot be negative")


@dataclass(frozen=True, slots=True)
class ReleaseRegressionState:
    schema_version: int
    source_manifest_digest: str
    test_inventory_sha256: str
    runtime_sha256: str
    shard_size: int
    planned_shards: tuple[ReleaseRegressionShardPlan, ...]
    completed_shards: tuple[ReleaseRegressionShardResult, ...]

    @property
    def tests_collected(self) -> int:
        return sum(item.collected for item in self.completed_shards)

    @property
    def plan_sha256(self) -> str:
        return regression_plan_digest(self.planned_shards)

    def matches(
        self,
        *,
        source_manifest_digest: str,
        test_inventory_sha256: str,
        runtime_sha256: str,
        shard_size: int,
    ) -> bool:
        return (
            self.schema_version == REGRESSION_STATE_SCHEMA_VERSION
            and self.source_manifest_digest == source_manifest_digest
            and self.test_inventory_sha256 == test_inventory_sha256
            and self.runtime_sha256 == runtime_sha256
            and self.shard_size == int(shard_size)
        )

    def result_for(self, shard_index: int, shard_identity_sha256: str) -> ReleaseRegressionShardResult | None:
        for result in self.completed_shards:
            if result.shard_index == shard_index and result.shard_identity_sha256 == shard_identity_sha256:
                return result
        return None

    def with_result(self, result: ReleaseRegressionShardResult) -> "ReleaseRegressionState":
        retained = tuple(item for item in self.completed_shards if item.shard_index != result.shard_index)
        return ReleaseRegressionState(
            schema_version=self.schema_version,
            source_manifest_digest=self.source_manifest_digest,
            test_inventory_sha256=self.test_inventory_sha256,
            runtime_sha256=self.runtime_sha256,
            shard_size=self.shard_size,
            planned_shards=self.planned_shards,
            completed_shards=tuple(sorted((*retained, result), key=lambda item: item.shard_index)),
        )

    def with_plan(self, planned_shards: tuple[ReleaseRegressionShardPlan, ...]) -> "ReleaseRegressionState":
        seen: set[str] = set()
        indexes: set[int] = set()
        for shard in planned_shards:
            if shard.shard_index in indexes:
                raise ValueError("release regression shard plan contains duplicate indexes")
            indexes.add(shard.shard_index)
            overlap = seen.intersection(shard.relative_test_files)
            if overlap:
                raise ValueError(f"release regression shard plan overlaps: {sorted(overlap)[0]}")
            seen.update(shard.relative_test_files)
        return ReleaseRegressionState(
            schema_version=self.schema_version,
            source_manifest_digest=self.source_manifest_digest,
            test_inventory_sha256=self.test_inventory_sha256,
            runtime_sha256=self.runtime_sha256,
            shard_size=self.shard_size,
            planned_shards=tuple(sorted(planned_shards, key=lambda item: item.shard_index)),
            completed_shards=self.completed_shards,
        )

    def to_json_bytes(self) -> bytes:
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def test_inventory_digest(relative_test_files: tuple[str, ...]) -> str:
    raw = "\n".join(relative_test_files).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def shard_identity_digest(relative_test_files: tuple[str, ...]) -> str:
    if not relative_test_files:
        raise ValueError("release regression shard cannot be empty")
    raw = "\n".join(relative_test_files).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def regression_plan_digest(planned_shards: tuple[ReleaseRegressionShardPlan, ...]) -> str:
    if not planned_shards:
        return hashlib.sha256(b"release-regression-plan:empty").hexdigest()
    raw = json.dumps(
        [
            {
                "shard_index": row.shard_index,
                "isolation_class": row.isolation_class,
                "relative_test_files": row.relative_test_files,
            }
            for row in sorted(planned_shards, key=lambda item: item.shard_index)
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def default_regression_state_path(root: Path) -> Path:
    resolved = Path(root).resolve()
    return resolved.parent / f".{resolved.name}.release-regression-state.json"


def _decode_planned_shards(raw_rows: list[object], *, legacy_parallel_bool: bool = False) -> tuple[ReleaseRegressionShardPlan, ...]:
    planned: list[ReleaseRegressionShardPlan] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise TypeError("planned shard must be an object")
        raw_files = raw["relative_test_files"]
        if not isinstance(raw_files, list):
            raise TypeError("planned shard files must be a list")
        if legacy_parallel_bool:
            isolation_class = "parallel-safe" if bool(raw.get("parallel_safe", False)) else "exclusive"
        else:
            isolation_class = str(raw["isolation_class"])
        planned.append(
            ReleaseRegressionShardPlan(
                shard_index=int(raw["shard_index"]),
                relative_test_files=tuple(str(value) for value in raw_files),
                isolation_class=isolation_class,
            )
        )
    return tuple(planned)


def decode_regression_state(raw: bytes) -> ReleaseRegressionState:
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("regression state must be an object")
        schema_version = int(payload.get("schema_version", 0))
        shards_raw = payload.get("completed_shards")
        if not isinstance(shards_raw, list):
            raise TypeError("completed_shards must be a list")

        completed: list[ReleaseRegressionShardResult] = []
        if schema_version == 1:
            for item in shards_raw:
                if not isinstance(item, dict):
                    raise TypeError("shard result must be an object")
                passed = int(item["passed"])
                skipped = int(item["skipped"])
                completed.append(
                    ReleaseRegressionShardResult(
                        shard_index=int(item["shard_index"]),
                        shard_identity_sha256=str(item["shard_identity_sha256"]),
                        first_test_file=str(item["first_test_file"]),
                        last_test_file=str(item["last_test_file"]),
                        collected=passed + skipped,
                        passed=passed,
                        skipped=skipped,
                        duration_seconds=0.0,
                    )
                )
        elif schema_version in {2, 3, REGRESSION_STATE_SCHEMA_VERSION}:
            completed = [ReleaseRegressionShardResult(**item) for item in shards_raw]
        else:
            raise ValueError(f"unsupported regression state schema {schema_version}")

        planned_raw = payload.get("planned_shards", []) if schema_version >= 3 else []
        if not isinstance(planned_raw, list):
            raise TypeError("planned_shards must be a list")
        planned = _decode_planned_shards(planned_raw, legacy_parallel_bool=schema_version == 3)
        return ReleaseRegressionState(
            schema_version=REGRESSION_STATE_SCHEMA_VERSION,
            source_manifest_digest=str(payload["source_manifest_digest"]),
            test_inventory_sha256=str(payload["test_inventory_sha256"]),
            runtime_sha256=str(payload["runtime_sha256"]),
            shard_size=int(payload["shard_size"]),
            planned_shards=planned,
            completed_shards=tuple(completed),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("release regression state violates its schema") from exc


def load_regression_state(path: Path) -> ReleaseRegressionState | None:
    path = Path(path)
    if not path.exists():
        return None
    return decode_regression_state(path.read_bytes())


def write_regression_state(path: Path, state: ReleaseRegressionState) -> None:
    atomic_replace_bytes(Path(path), state.to_json_bytes())


def clear_regression_state(path: Path) -> None:
    durable_unlink(Path(path))


__all__ = [
    "REGRESSION_STATE_SCHEMA_VERSION",
    "ReleaseRegressionShardPlan",
    "ReleaseRegressionShardResult",
    "ReleaseRegressionState",
    "clear_regression_state",
    "decode_regression_state",
    "default_regression_state_path",
    "load_regression_state",
    "regression_plan_digest",
    "shard_identity_digest",
    "test_inventory_digest",
    "write_regression_state",
]
