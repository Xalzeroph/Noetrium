from __future__ import annotations

import hashlib

from research.benchmarks.toolbench import (
    TOOLBENCH_PAPER_CODE_COMMIT,
    TOOLBENCH_SUBSETS,
    TOOLBENCH_TOOLEVAL_COMMIT,
    ToolBenchTaskRecord,
    build_toolbench_source,
    build_toolbench_task_set,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _records() -> tuple[ToolBenchTaskRecord, ...]:
    return tuple(
        ToolBenchTaskRecord(
            query_id=f"q{index}",
            subset_id=subset,
            content_digest=_digest(f"task:{subset}"),
            oracle_api_set_digest=_digest(f"apis:{subset}"),
            oracle_api_count=index + 1,
        )
        for index, subset in enumerate(TOOLBENCH_SUBSETS)
    )


def test_toolbench_cut_binds_six_official_subsets_and_tooleval_identity() -> None:
    content = _digest("toolbench-paper-cut")
    task_set = build_toolbench_task_set(
        _records(),
        dataset_revision="paper-eval-cut",
        dataset_content_sha256=content,
        api_binding_mode="oracle",
    )
    assert task_set.benchmark_id == "toolbench"
    assert tuple(split.split_id for split in task_set.splits) == TOOLBENCH_SUBSETS
    assert all(len(split.task_ids) == 1 for split in task_set.splits)
    assert TOOLBENCH_PAPER_CODE_COMMIT in task_set.revision_id
    assert TOOLBENCH_TOOLEVAL_COMMIT in task_set.revision_id

    for task in task_set.tasks:
        assert task.package is not None
        assert (
            task.package.environment_requirement_id
            == "benchmark.toolbench.rapidapi.environment"
        )
        assert (
            task.package.verifier_requirement_id
            == "benchmark.toolbench.tooleval.verifier"
        )
        assert task.package.artifacts[0].relative_path == "answer_generation.json"


def test_toolbench_source_separates_dataset_cut_api_binding_and_evaluator() -> None:
    source = build_toolbench_source(
        dataset_revision="paper-eval-cut",
        dataset_content_sha256=_digest("toolbench-paper-cut"),
        api_binding_mode="retrieved-top5",
    )
    assert source.metadata["paper_code_commit"] == TOOLBENCH_PAPER_CODE_COMMIT
    assert source.metadata["tooleval_commit"] == TOOLBENCH_TOOLEVAL_COMMIT
    assert source.metadata["api_binding_mode"] == "retrieved-top5"
    assert source.metadata["paper_metrics"] == "pass_rate,win_rate"
    assert source.metadata["external_environment"] == "RapidAPI"


def test_toolbench_cut_identity_changes_with_oracle_api_set() -> None:
    rows = _records()
    left = build_toolbench_task_set(
        rows,
        dataset_revision="paper-eval-cut",
        dataset_content_sha256=_digest("toolbench-paper-cut"),
    )
    changed = list(rows)
    first = changed[0]
    changed[0] = ToolBenchTaskRecord(
        query_id=first.query_id,
        subset_id=first.subset_id,
        content_digest=first.content_digest,
        oracle_api_set_digest=_digest("different-api-set"),
        oracle_api_count=first.oracle_api_count,
    )
    right = build_toolbench_task_set(
        tuple(changed),
        dataset_revision="paper-eval-cut",
        dataset_content_sha256=_digest("toolbench-paper-cut"),
    )
    assert left.cut_digest != right.cut_digest
