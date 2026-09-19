from __future__ import annotations

from noetrium_platform.research.provenance import MethodSourceLaneKind
from noetrium_platform.research.reproduction import ReproductionAssetKind
from research.reproductions.aflow.definition import REPRODUCTION
from research.reproductions.aflow.fidelity import (
    AFLOW_FIDELITY,
    AFLOW_PAPER_ERA_COMMIT,
)
from research.reproductions.aflow.source import (
    AFLOW_ICLR_2025,
    AFLOW_PAPER_ERA_METAGPT,
    AFLOW_REVIEW_REVISION,
    AFLOW_STANDALONE_MIGRATION,
    SOURCES,
)


def test_aflow_formal_lane_is_paper_era_metagpt_not_standalone_migration() -> None:
    assert AFLOW_PAPER_ERA_COMMIT == (
        "072839af7f75948d91d3784154128ab2456831f0"
    )
    assert AFLOW_PAPER_ERA_METAGPT.kind is MethodSourceLaneKind.OFFICIAL_EXECUTABLE
    assert AFLOW_PAPER_ERA_METAGPT.commit == AFLOW_PAPER_ERA_COMMIT
    assert AFLOW_REVIEW_REVISION.kind is MethodSourceLaneKind.LATER_RELEASED_EXECUTABLE
    assert AFLOW_STANDALONE_MIGRATION.kind is MethodSourceLaneKind.LATER_RELEASED_EXECUTABLE
    assert AFLOW_ICLR_2025.executable is False
    assert len(SOURCES.lanes) == 4


def test_aflow_fidelity_freezes_search_round_sampling_and_evaluation_semantics() -> None:
    fidelity = AFLOW_FIDELITY
    assert fidelity.datasets == (
        "HumanEval",
        "MBPP",
        "GSM8K",
        "MATH",
        "HotpotQA",
        "DROP",
    )
    assert fidelity.search_object == "python_workflow_source"
    assert fidelity.workflow_representation == "code"
    assert (
        fidelity.initial_round,
        fidelity.optimization_iterations,
        fidelity.maximum_materialized_round,
    ) == (1, 20, 21)
    assert (
        fidelity.parent_pool_size,
        fidelity.score_scale,
        fidelity.softmax_alpha,
        fidelity.uniform_mix_weight,
        fidelity.score_softmax_weight,
    ) == (4, 100.0, 0.2, 0.3, 0.7)
    assert fidelity.validation_repetitions == 5
    assert fidelity.test_repetitions == 3
    assert (
        fidelity.convergence_top_k,
        fidelity.convergence_z,
        fidelity.convergence_consecutive_rounds,
    ) == (3, 0.0, 5)
    assert fidelity.optimizer_model == "claude-3-5-sonnet-20240620"
    assert fidelity.execution_model == "gpt-4o-mini"
    assert fidelity.parent_sampling_explicitly_seeded is False
    assert fidelity.failure_log_sampling_explicitly_seeded is False
    assert len(fidelity.fidelity_digest) == 64


def test_aflow_reproduction_uses_universal_research_program_asset() -> None:
    kinds = tuple(asset.kind for asset in REPRODUCTION.assets)
    assert ReproductionAssetKind.FIDELITY in kinds
    assert ReproductionAssetKind.RESEARCH_PROGRAM in kinds
    assert ReproductionAssetKind.METHOD_PROGRAM not in kinds
    assert REPRODUCTION.lifecycle.value == "protocol_bound"
    assert "humaneval" in REPRODUCTION.catalog.benchmark_ids
