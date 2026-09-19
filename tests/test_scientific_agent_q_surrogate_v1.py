from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.benchmarks.webvoyager import (
    WEBVOYAGER_AGENT_Q_SURROGATE_REVISION,
    WEBVOYAGER_AGENT_Q_SURROGATE_SPLIT,
    WEBVOYAGER_AGENT_Q_SURROGATE_TASK_COUNT,
    WebVoyagerTaskRecord,
    build_agent_q_surrogate_webvoyager_task_set,
)
from research.reproductions.agent_q_surrogate import (
    AGENT_Q_SURROGATE_FIDELITY,
    build_agent_q_surrogate_webvoyager_study,
)


def _benchmark():
    return build_agent_q_surrogate_webvoyager_task_set(
        tuple(
            WebVoyagerTaskRecord(
                index=index,
                start_url=f"https://example.com/task/{index}",
                content_digest=canonical_digest({"webvoyager-task": index}),
            )
            for index in range(WEBVOYAGER_AGENT_Q_SURROGATE_TASK_COUNT)
        ),
        source_digest=canonical_digest({"agent-q-surrogate-webvoyager": 1}),
    )


def test_agent_q_surrogate_can_never_be_mislabelled_as_official_source() -> None:
    fidelity = AGENT_Q_SURROGATE_FIDELITY
    assert fidelity.source.kind.value == "surrogate"
    assert fidelity.official_source_resolved is False
    assert fidelity.relation_to_paper == "independent_oss_surrogate_not_author_official"


def test_agent_q_distinguishes_core_defaults_from_browser_invocation() -> None:
    fidelity = AGENT_Q_SURROGATE_FIDELITY
    assert (
        fidelity.core_mcts_iterations_default,
        fidelity.core_mcts_depth_default,
        fidelity.core_mcts_simulation_default,
    ) == (10, 5, "random")
    assert (
        fidelity.browser_invocation_iterations,
        fidelity.browser_invocation_depth,
        fidelity.browser_invocation_simulation,
    ) == (10, 6, "max")
    assert fidelity.terminal_judge_model == "gpt-4o-2024-08-06"


def test_agent_q_surrogate_webvoyager_study_separates_provenance_from_execution_design() -> None:
    benchmark = _benchmark()
    study = build_agent_q_surrogate_webvoyager_study(benchmark)
    assert benchmark.revision_id == WEBVOYAGER_AGENT_Q_SURROGATE_REVISION
    assert len(benchmark.selected_tasks(WEBVOYAGER_AGENT_Q_SURROGATE_SPLIT)) == 643
    assert not hasattr(study, "method_source_lane")
    assert AGENT_Q_SURROGATE_FIDELITY.source.kind.value == "surrogate"
    roles = {row.role: row.requirement_id for row in study.binding_requirements.model_roles}
    assert roles == {
        "actor": "model.agent-q-surrogate.actor",
        "critic": "model.agent-q-surrogate.critic",
        "vision_judge": "model.agent-q-surrogate.vision-judge",
    }
    assert study.execution_policy.trial_budget.max_steps == 6
