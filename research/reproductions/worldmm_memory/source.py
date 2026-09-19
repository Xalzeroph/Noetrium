from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

WORLDMM_INITIAL_RELEASE_COMMIT = (
    "5a5f779026d51024746e7b3fab7959dd0beedcd7"
)
WORLDMM_SEMANTIC_INDEX_REPAIR_COMMIT = (
    "245faf6ce3309c1c87e205c634af230fdae69c71"
)

WORLDMM_CVPR_2026 = PublicationSourceLane(
    lane_id="cvpr_2026_final",
    venue="CVPR",
    year=2026,
    publication_id="worldmm-cvpr-2026",
    publication_uri=(
        "https://openaccess.thecvf.com/content/CVPR2026/html/"
        "Yeo_WorldMM_Dynamic_Multimodal_Memory_Agent_for_Long_"
        "Video_Reasoning_CVPR_2026_paper.html"
    ),
    revision="CVPR 2026 camera-ready publication",
)

WORLDMM_INITIAL_EXECUTABLE = MethodSourceLane(
    lane_id="initial_public_executable",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/wgcyeo/WorldMM",
    commit=WORLDMM_INITIAL_RELEASE_COMMIT,
    artifacts=(
        "src/worldmm/memory/memory.py",
        "src/worldmm/memory/episodic/memory.py",
        "src/worldmm/memory/episodic/multiscale.py",
        "src/worldmm/memory/semantic/memory.py",
        "src/worldmm/memory/semantic/semantic_extraction.py",
        "src/worldmm/memory/semantic/semantic_consolidation.py",
        "src/worldmm/memory/visual/memory.py",
        "src/worldmm/llm/templates/memory_reasoning.py",
        "src/worldmm/llm/templates/multiscale_filter.py",
        "eval/eval.py",
    ),
)

WORLDMM_SEMANTIC_INDEX_REPAIR = MethodSourceLane(
    lane_id="semantic_index_repair",
    kind=MethodSourceLaneKind.LATER_RELEASED_EXECUTABLE,
    repository="https://github.com/wgcyeo/WorldMM",
    commit=WORLDMM_SEMANTIC_INDEX_REPAIR_COMMIT,
    artifacts=("src/worldmm/memory/semantic/memory.py",),
)

SOURCES = MethodSourceRegistry(
    lanes=(
        WORLDMM_CVPR_2026,
        WORLDMM_INITIAL_EXECUTABLE,
        WORLDMM_SEMANTIC_INDEX_REPAIR,
    ),
)

__all__ = [
    "SOURCES",
    "WORLDMM_CVPR_2026",
    "WORLDMM_INITIAL_EXECUTABLE",
    "WORLDMM_INITIAL_RELEASE_COMMIT",
    "WORLDMM_SEMANTIC_INDEX_REPAIR",
    "WORLDMM_SEMANTIC_INDEX_REPAIR_COMMIT",
]
