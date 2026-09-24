from __future__ import annotations

import json

import pytest

from noetrium_platform.foundation.governance.analysis.algorithm.providers.filesystem import (
    _snapshot_from_dict,
)
from noetrium_platform.foundation.governance.analysis.concurrency.providers.filesystem import (
    FilesystemConcurrencySnapshotStore,
)
from noetrium_platform.foundation.governance.analysis.performance.providers.filesystem import (
    FilesystemPerformanceSnapshotStore,
)
from noetrium_platform.foundation.governance.release.runtime.regression_state import (
    decode_regression_state,
)


def test_algorithm_snapshot_v2_is_not_compatibly_decoded() -> None:
    with pytest.raises(
        ValueError,
        match="unsupported algorithm snapshot schema",
    ):
        _snapshot_from_dict({"schema_version": "algorithm-snapshot.v2"})


@pytest.mark.parametrize(
    ("store_type", "schema"),
    (
        (FilesystemConcurrencySnapshotStore, "concurrency-baseline.v1"),
        (FilesystemPerformanceSnapshotStore, "performance-baseline.v1"),
    ),
)
def test_governance_baseline_old_schema_fails_closed(
    tmp_path,
    store_type,
    schema,
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "schema_version": schema,
                "analyzer_revision": "old",
                "blocker_fingerprints": [],
            }
        ),
        encoding="utf-8",
    )
    store = store_type(tmp_path / "state", baseline_path=baseline)
    with pytest.raises(ValueError, match="unsupported .* baseline schema"):
        store.load_baseline()


def test_release_regression_v3_is_not_upgraded_in_place() -> None:
    payload = {
        "schema_version": 3,
        "source_manifest_digest": "source",
        "test_inventory_sha256": "inventory",
        "runtime_sha256": "runtime",
        "shard_size": 1,
        "planned_shards": [],
        "completed_shards": [],
    }
    with pytest.raises(
        ValueError,
        match="release regression state violates its schema",
    ):
        decode_regression_state(json.dumps(payload).encode("utf-8"))
