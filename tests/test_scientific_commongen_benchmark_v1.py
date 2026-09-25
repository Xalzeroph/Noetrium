from __future__ import annotations

from research.benchmarks.commongen import (
    COMMONGEN_BENCHMARK_ID,
    CommonGenTaskRecord,
    build_commongen_task_set,
)
from research.reproductions.self_refine import build_self_refine_commongen_study


def _sha(char: str) -> str:
    return char * 64


def test_commongen_cut_binds_concepts_splits_and_separate_verifier() -> None:
    benchmark = build_commongen_task_set(
        (
            CommonGenTaskRecord(
                "commongen:dev:1",
                "self-refine-hard",
                ("beat", "drum", "pen", "sit", "use"),
                _sha("1"),
                3,
            ),
            CommonGenTaskRecord(
                "commongen:dev:2",
                "self-refine-hard",
                ("chair", "clipper", "cut", "hair", "sit"),
                _sha("2"),
                3,
            ),
        ),
        dataset_revision="paper-self-refine-hard-v1",
        dataset_content_sha256=_sha("a"),
    )

    assert benchmark.benchmark_id == COMMONGEN_BENCHMARK_ID
    selected = benchmark.selected_tasks("self-refine-hard")
    assert tuple(row.task_id for row in selected) == (
        "commongen:dev:1",
        "commongen:dev:2",
    )
    assert all(
        row.package is not None
        and row.package.verifier_requirement_id == "benchmark.commongen.verifier"
        for row in selected
    )

    study = build_self_refine_commongen_study(
        benchmark,
        split_id="self-refine-hard",
    )
    assert study.benchmark.cut_digest == benchmark.cut_digest
    assert study.benchmark_split_id == "self-refine-hard"
    model_roles = study.binding_requirements.model_roles
    assert len(model_roles) == 1
    assert model_roles[0].role == "self-refine.model"
    assert model_roles[0].requirement_id == "model.self-refine.shared"
    assert study.execution_policy.trial_budget.max_model_calls == 8
