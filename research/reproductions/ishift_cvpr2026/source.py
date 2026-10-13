from __future__ import annotations
from research.reproductions.provenance import MethodSourceLane, MethodSourceLaneKind, MethodSourceRegistry, PublicationSourceLane
PUBLICATION=PublicationSourceLane(lane_id="final_publication",venue="CVPR",year=2026,publication_id="Mehrotra_iSHIFT_CVPR_2026",publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Mehrotra_iSHIFT_Lightweight_Slow-Fast_GUI_Agent_with_Adaptive_Perception_CVPR_2026_paper.html",revision="CVPR 2026 final proceedings paper")
OFFICIAL_REPOSITORY_CUT=MethodSourceLane(lane_id="official_repository_cut",kind=MethodSourceLaneKind.OFFICIAL_ARTIFACT,repository="https://github.com/SarthakM320/iSHIFT",commit="d77267511fdb27cd46c030990bffe8d025fb8489",artifacts=("README.md",))
SOURCES=MethodSourceRegistry(lanes=(PUBLICATION,OFFICIAL_REPOSITORY_CUT))
__all__=["PUBLICATION","SOURCES"]
