from __future__ import annotations

import hashlib

import pytest

from research.benchmarks.humaneval import (
    HUMANEVAL_PAPER_ERA_COMMIT,
    HUMANEVAL_SPLIT_ID,
    HUMANEVAL_TASK_COUNT,
    HumanEvalTaskRecord,
    build_humaneval_task_set,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _records() -> tuple[HumanEvalTaskRecord, ...]:
    return tuple(
        HumanEvalTaskRecord(
            index=index,
            task_id=f"HumanEval/{index}",
            entry_point=f"fn_{index}",
            content_digest=_digest(f"HumanEval/{index}:fn_{index}"),
        )
        for index in range(HUMANEVAL_TASK_COUNT)
    )


def test_humaneval_cut_freezes_all_164_tasks_and_separate_verifier() -> None:
    task_set = build_humaneval_task_set(
        _records(),
        dataset_content_sha256=_digest("HumanEval.jsonl.gz"),
    )
    assert task_set.benchmark_id == "humaneval"
    assert HUMANEVAL_PAPER_ERA_COMMIT in task_set.revision_id
    selected = task_set.selected_tasks(HUMANEVAL_SPLIT_ID)
    assert len(selected) == 164
    assert selected[0].task_id == "HumanEval/0"
    assert selected[-1].task_id == "HumanEval/163"
    assert all(
        task.package.verifier_requirement_id
        == "benchmark.humaneval.functional-correctness.verifier"
        for task in selected
    )
    assert all(
        task.package.environment_requirement_id
        == "benchmark.humaneval.python-sandbox"
        for task in selected
    )


def test_humaneval_cut_rejects_incomplete_task_identity() -> None:
    with pytest.raises(ValueError, match="exactly 164"):
        build_humaneval_task_set(
            _records()[:-1],
            dataset_content_sha256=_digest("HumanEval.jsonl.gz"),
        )
