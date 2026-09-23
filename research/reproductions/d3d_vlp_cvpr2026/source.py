from __future__ import annotations
from research.reproductions.provenance import MethodSourceLane, MethodSourceLaneKind, MethodSourceRegistry, PublicationSourceLane
PUBLICATION=PublicationSourceLane(lane_id="final_publication",venue="CVPR",year=2026,publication_id="Wang_D3D_VLP_CVPR_2026",publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wang_D3D-VLP_Dynamic_3D_Vision-Language-Planning_Model_for_Embodied_Grounding_and_Navigation_CVPR_2026_paper.html",revision="CVPR 2026 final proceedings paper")
OFFICIAL_REPOSITORY_CUT=MethodSourceLane(lane_id="official_repository_cut",kind=MethodSourceLaneKind.OFFICIAL_ARTIFACT,repository="https://github.com/MrZihan/D3D-VLP",commit="0c285fe32bef11ea9067fb74d7c12edc46be5d1a",artifacts=("README.md",))
SOURCES=MethodSourceRegistry(lanes=(PUBLICATION,OFFICIAL_REPOSITORY_CUT))
__all__=["PUBLICATION","SOURCES"]
