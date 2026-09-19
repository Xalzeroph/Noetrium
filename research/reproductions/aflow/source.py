from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

AFLOW_ICLR_2025 = PublicationSourceLane(
    lane_id="iclr_2025_final",
    venue="ICLR",
    year=2025,
    publication_id="5492ecbce4439401798dcd2c90be94cd",
    publication_uri=(
        "https://proceedings.iclr.cc/paper_files/paper/2025/hash/"
        "5492ecbce4439401798dcd2c90be94cd-Abstract-Conference.html"
    ),
    revision="ICLR 2025 final paper",
)

AFLOW_PAPER_ERA_METAGPT = MethodSourceLane(
    lane_id="paper_era_metagpt_final",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/FoundationAgents/MetaGPT",
    commit="072839af7f75948d91d3784154128ab2456831f0",
    artifacts=(
        "examples/aflow/experiments/optimize_humaneval.py",
        "metagpt/ext/aflow/benchmark/humaneval.py",
        "metagpt/ext/aflow/scripts/evaluator.py",
        "metagpt/ext/aflow/scripts/operator.py",
        "metagpt/ext/aflow/scripts/optimizer.py",
        "metagpt/ext/aflow/scripts/optimizer_utils/convergence_utils.py",
        "metagpt/ext/aflow/scripts/optimizer_utils/data_utils.py",
        "metagpt/ext/aflow/scripts/optimizer_utils/evaluation_utils.py",
        "metagpt/ext/aflow/scripts/optimizer_utils/experience_utils.py",
        "metagpt/ext/aflow/scripts/optimizer_utils/graph_utils.py",
        "metagpt/ext/aflow/scripts/prompts/optimize_prompt.py",
        "metagpt/ext/aflow/scripts/workflow.py",
    ),
)

AFLOW_REVIEW_REVISION = MethodSourceLane(
    lane_id="review_revision_metagpt",
    kind=MethodSourceLaneKind.LATER_RELEASED_EXECUTABLE,
    repository="https://github.com/FoundationAgents/MetaGPT",
    commit="d01051abc612ba9c6c284e9827c0b7091cb83d87",
    artifacts=(
        "examples/aflow/experiments/optimize_humaneval.py",
        "metagpt/ext/aflow/scripts/optimizer.py",
        "metagpt/ext/aflow/scripts/workflow.py",
    ),
)

AFLOW_STANDALONE_MIGRATION = MethodSourceLane(
    lane_id="standalone_repository_migration",
    kind=MethodSourceLaneKind.LATER_RELEASED_EXECUTABLE,
    repository="https://github.com/FoundationAgents/AFlow",
    commit="383b65af61c06b24c71815ab7447fb835ba2c73b",
    artifacts=(
        "README.md",
        "run.py",
        "scripts/evaluator.py",
        "scripts/operator.py",
        "scripts/optimizer.py",
        "scripts/workflow.py",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(
        AFLOW_ICLR_2025,
        AFLOW_PAPER_ERA_METAGPT,
        AFLOW_REVIEW_REVISION,
        AFLOW_STANDALONE_MIGRATION,
    ),
)

__all__ = [
    "AFLOW_ICLR_2025",
    "AFLOW_PAPER_ERA_METAGPT",
    "AFLOW_REVIEW_REVISION",
    "AFLOW_STANDALONE_MIGRATION",
    "SOURCES",
]
