from __future__ import annotations
from research.reproductions.provenance import MethodSourceLane, MethodSourceLaneKind, MethodSourceRegistry, PublicationSourceLane
PUBLICATION=PublicationSourceLane(lane_id="final_publication",venue="CVPR",year=2026,publication_id="Wu_See_Think_Act_CVPR_2026",publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_See_Think_Act_Teaching_Multimodal_Agents_to_Effectively_Interact_with_CVPR_2026_paper.html",revision="CVPR 2026 final proceedings paper")

OFFICIAL_REPOSITORY_CUT=MethodSourceLane(lane_id="official_repository_cut",kind=MethodSourceLaneKind.OFFICIAL_ARTIFACT,repository="https://github.com/ZrW00/StaR",commit="3af0acd5c393c5eaa5253f411d7c22fba35b6f67",artifacts=("README.md",))

SOURCES=MethodSourceRegistry(lanes=(PUBLICATION, OFFICIAL_REPOSITORY_CUT,))
__all__=["PUBLICATION","SOURCES"]
