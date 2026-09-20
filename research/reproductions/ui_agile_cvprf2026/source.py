from __future__ import annotations
from noetrium_platform.research.provenance import MethodSourceLane, MethodSourceLaneKind, MethodSourceRegistry, PublicationSourceLane
PUBLICATION=PublicationSourceLane(lane_id="final_publication",venue="CVPR Findings",year=2026,publication_id="Lian_UI_AGILE_CVPRF_2026",publication_uri="https://openaccess.thecvf.com/content/CVPR2026F/html/Lian_UI-AGILE_Advancing_GUI_Agents_with_Effective_Reinforcement_Learning_and_Precise_CVPRF_2026_paper.html",revision="CVPR Findings 2026 final proceedings paper")
OFFICIAL_REPOSITORY_CUT=MethodSourceLane(lane_id="official_repository_cut",kind=MethodSourceLaneKind.OFFICIAL_ARTIFACT,repository="https://github.com/KDEGroup/UI-AGILE",commit="3a397b078d6c14338f0646070212f8c3eb837881",artifacts=("README.md",))
SOURCES=MethodSourceRegistry(lanes=(PUBLICATION,OFFICIAL_REPOSITORY_CUT))
__all__=["PUBLICATION","SOURCES"]
