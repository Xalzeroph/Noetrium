from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.benchmarks.math500 import (
    MATH500_EXPECTED_TASK_COUNT,
    MATH500_LITS_REVISION,
    Math500TaskRecord,
    build_math500_lits_task_set,
)
from research.reproductions.lits_math500 import (
    LITS_MATH500_RELEASE_FIDELITY,
    build_lits_math500_release_study,
)


def _benchmark():
    return build_math500_lits_task_set(
        tuple(
            Math500TaskRecord(
                index=index,
                content_digest=canonical_digest({"math500": index}),
                level=str(index % 5 + 1),
            )
            for index in range(MATH500_EXPECTED_TASK_COUNT)
        ),
        source_digest=canonical_digest({"math500-source": "xinzhel/math500-float:test"}),
    )


def test_lits_paper_era_release_keeps_component_abi_search_budget_and_source_identity() -> None:
    fidelity = LITS_MATH500_RELEASE_FIDELITY
    assert fidelity.source.kind.value == "official_executable"
    assert fidelity.source.commit == "4f522bb7bf5d5bfd68c42649efe44c566dfa039c"
    assert fidelity.core_component_contracts == ("Policy", "Transition", "RewardModel")
    assert fidelity.supported_search_algorithms == ("mcts", "bfs")
    assert (fidelity.search_iterations, fidelity.candidate_actions, fidelity.max_steps) == (50, 3, 10)


def test_lits_math500_release_compiles_without_inventing_a_concrete_model() -> None:
    benchmark = _benchmark()
    study = build_lits_math500_release_study(benchmark)
    assert benchmark.revision_id == MATH500_LITS_REVISION
    assert len(benchmark.tasks) == 500
    assert study.execution_policy.trial_budget.max_steps == 10
    assert not hasattr(study, "method_source_lane")
    assert LITS_MATH500_RELEASE_FIDELITY.source.kind.value == "official_executable"
    roles = {row.role: row.requirement_id for row in study.binding_requirements.model_roles}
    assert roles == {"policy": "model.lits.policy", "reward": "model.lits.reward"}
    assert LITS_MATH500_RELEASE_FIDELITY.model_binding_semantics.endswith("concrete_model_is_user_bound")
