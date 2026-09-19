from __future__ import annotations

import pytest

from noetrium_platform.research.experimentation.study.api import TaskVerifierIsolation
from research.benchmarks.gsm8k import (
    GSM8K_ARCHIVED_COMMIT,
    GSM8K_BENCHMARK_ID,
    GSM8K_RELEASE_COMMIT,
    GSM8KTaskRecord,
    build_gsm8k_task_set,
)


def _row(split_id: str, index: int, token: str) -> GSM8KTaskRecord:
    return GSM8KTaskRecord(
        split_id,
        index,
        token * 64,
        chr(ord(token) + 1) * 64,
        chr(ord(token) + 2) * 64,
    )


def test_gsm8k_cut_freezes_official_repository_and_verifier_semantics() -> None:
    cut = build_gsm8k_task_set(
        (_row("test", 0, "1"), _row("test", 1, "4")),
        dataset_content_sha256="a" * 64,
        require_full_split_cardinality=False,
    )

    assert cut.benchmark_id == GSM8K_BENCHMARK_ID
    assert GSM8K_RELEASE_COMMIT == "b0bb162abedc65e1fdd8e93ed090fd7598ee68bc"
    assert GSM8K_ARCHIVED_COMMIT == "3101c7d5072418e28b9008a6636bde82a006892c"
    assert cut.selected_tasks("test")[0].task_id == "gsm8k:test:00000"
    package = cut.selected_tasks("test")[0].package
    assert package is not None
    assert package.verifier_requirement_id == "benchmark.gsm8k.exact-numeric.verifier"
    assert package.verifier_isolation is TaskVerifierIsolation.SEPARATE
    assert any(ref == "answer-marker:####" for ref in cut.tasks[0].lineage_refs)


def test_gsm8k_full_cut_rejects_partial_split_when_claiming_paper_cardinality() -> None:
    with pytest.raises(ValueError, match="requires 1319 tasks"):
        build_gsm8k_task_set(
            (_row("test", 0, "1"),),
            dataset_content_sha256="b" * 64,
        )
