from __future__ import annotations

from noetrium_platform.research.experimentation.identity import ModelRoleUsage
from research.benchmarks.camel_ai_society import (
    CAMEL_AI_SOCIETY_BENCHMARK_ID,
    CAMEL_AI_SOCIETY_SPLIT_ID,
    CamelAISocietyTaskRecord,
    build_camel_ai_society_task_set,
)
from research.reproductions.camel_role_playing import build_camel_ai_society_study


def _sha(seed: int) -> str:
    return f"{seed:064x}"[-64:]


def _records() -> tuple[CamelAISocietyTaskRecord, ...]:
    rows = []
    index = 1
    for assistant in range(1, 11):
        for user in range(1, 11):
            rows.append(
                CamelAISocietyTaskRecord(
                    assistant,
                    user,
                    1,
                    f"Assistant Role {assistant}",
                    f"User Role {user}",
                    f"Task {assistant}-{user}",
                    _sha(index),
                )
            )
            index += 1
    return tuple(rows)


def test_camel_ai_society_cut_requires_exact_100_task_agent_evaluation() -> None:
    benchmark = build_camel_ai_society_task_set(
        _records(),
        dataset_content_sha256="a" * 64,
    )
    assert benchmark.benchmark_id == CAMEL_AI_SOCIETY_BENCHMARK_ID
    selected = benchmark.selected_tasks(CAMEL_AI_SOCIETY_SPLIT_ID)
    assert len(selected) == 100
    assert all(
        row.package is not None
        and row.package.verifier_requirement_id
        == "benchmark.camel-ai-society.pairwise-judge"
        for row in selected
    )


def test_camel_study_keeps_execution_roles_on_shared_model_and_gpt4_evaluation_only() -> None:
    benchmark = build_camel_ai_society_task_set(
        _records(),
        dataset_content_sha256="b" * 64,
    )
    study = build_camel_ai_society_study(benchmark)

    roles = {row.role: row for row in study.binding_requirements.model_roles}
    execution_roles = {
        "camel.task-specifier",
        "camel.task-planner",
        "camel.assistant-agent",
        "camel.user-agent",
    }
    assert execution_roles.issubset(roles)
    assert {
        roles[name].requirement_id for name in execution_roles
    } == {"model.camel.gpt-3.5-turbo.paper-era"}
    assert all(
        roles[name].usage is ModelRoleUsage.EXECUTION
        for name in execution_roles
    )
    assert roles["camel.gpt4-judge"].usage is ModelRoleUsage.EVALUATION
    assert study.execution_policy.trial_budget.max_model_calls == 43
