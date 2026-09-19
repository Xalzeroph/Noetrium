from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceRegistry,
    PublicationSourceLane,
)

SOURCE_CVPR_2024_PAPER = PublicationSourceLane(
    lane_id="cvpr_2024_final",
    venue="CVPR",
    year=2024,
    publication_id="Hong_CogAgent_A_Visual_Language_Model_for_GUI_Agents_CVPR_2024",
    publication_uri=(
        "https://openaccess.thecvf.com/content/CVPR2024/html/"
        "Hong_CogAgent_A_Visual_Language_Model_for_GUI_Agents_CVPR_2024_paper.html"
    ),
    revision="CVPR 2024 final",
)

SOURCES = MethodSourceRegistry(lanes=(SOURCE_CVPR_2024_PAPER,))

__all__ = ["SOURCE_CVPR_2024_PAPER", "SOURCES"]
