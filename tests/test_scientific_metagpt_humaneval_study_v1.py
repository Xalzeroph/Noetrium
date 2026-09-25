from __future__ import annotations

import hashlib

from research.benchmarks.humaneval import (
    HumanEvalTaskRecord,
    build_humaneval_task_set,
)
from research.reproductions.metagpt_software_company import (
    build_metagpt_humaneval_study,
    metagpt_humaneval_trial_protocol,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _benchmark():
    records = tuple(
        HumanEvalTaskRecord(
            index=index,
            task_id=f"HumanEval/{index}",
            entry_point=f"fn_{index}",
            content_digest=_digest(f"task:{index}"),
        )
        for index in range(164)
    )
    return build_humaneval_task_set(
        records,
        dataset_content_sha256=_digest("human-eval-paper-data"),
    )


def test_metagpt_humaneval_study_binds_four_roles_artifact_capability_and_pass_at_1() -> None:
    benchmark = _benchmark()
    definition = build_metagpt_humaneval_study(benchmark, use_code_review=False)
    assert definition.benchmark_split_id == "test"
    assert len(definition.benchmark.selected_tasks("test")) == 164

    method = next(
        row
        for row in definition.binding_requirements.participants
        if row.role == "software_company"
    )
    assert method.capability_requirement_ids == ("artifact.publish",)

    roles = {row.role for row in definition.binding_requirements.participants}
    assert {
        "metagpt.product-manager",
        "metagpt.architect",
        "metagpt.project-manager",
        "metagpt.engineer",
    }.issubset(roles)

    assert {
        row.measurement_id for row in definition.measurement_protocol.definitions
    } == {"task_success", "artifact_count", "model_call_count"}


def test_metagpt_review_treatment_has_distinct_protocol_identity() -> None:
    benchmark = _benchmark()
    core = metagpt_humaneval_trial_protocol(benchmark, use_code_review=False)
    reviewed = metagpt_humaneval_trial_protocol(benchmark, use_code_review=True)
    assert core.protocol_id != reviewed.protocol_id
    assert core.configuration_digest != reviewed.configuration_digest

    review_study = build_metagpt_humaneval_study(
        benchmark,
        use_code_review=True,
    )
    budget = review_study.execution_policy.trial_budget
    assert budget.max_model_calls == 5
    assert budget.max_turns == 5
