from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)


OPTIMUS2_PAPER_REPOSITORY_COMMIT = (
    "8651b3177ac5c7fa73a36b74e4b350a35a679338"
)

OPTIMUS2_CVPR_2025 = PublicationSourceLane(
    lane_id="cvpr_2025_main",
    venue="CVPR",
    year=2025,
    publication_id="Li_2025_CVPR_Optimus2",
    publication_uri=(
        "https://openaccess.thecvf.com/content/CVPR2025/html/"
        "Li_Optimus-2_Multimodal_Minecraft_Agent_with_"
        "Goal-Observation-Action_Conditioned_Policy_CVPR_2025_paper.html"
    ),
    revision="CVPR 2025 camera-ready",
)

OPTIMUS2_PAPER_REPOSITORY = MethodSourceLane(
    lane_id="official_paper_repository_2025_02_28",
    kind=MethodSourceLaneKind.PAPER_PROVENANCE,
    repository="https://github.com/iLearn-Lab/CVPR25-Optimus-2",
    commit=OPTIMUS2_PAPER_REPOSITORY_COMMIT,
    artifacts=(
        "README.md",
        "assets/fig2.pdf",
        "assets/fig2.png",
        "assets/optimus2.png",
        "assets/table1.png",
        "assets/table2.png",
        "assets/table3.png",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(OPTIMUS2_CVPR_2025, OPTIMUS2_PAPER_REPOSITORY),
)


__all__ = [
    "OPTIMUS2_CVPR_2025",
    "OPTIMUS2_PAPER_REPOSITORY",
    "OPTIMUS2_PAPER_REPOSITORY_COMMIT",
    "SOURCES",
]
