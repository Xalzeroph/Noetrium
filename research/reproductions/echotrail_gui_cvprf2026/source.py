from __future__ import annotations
from noetrium_platform.research.provenance import MethodSourceRegistry, PublicationSourceLane
PUBLICATION=PublicationSourceLane(lane_id="final_publication",venue="CVPR Findings",year=2026,publication_id="Li_EchoTrail_GUI_CVPRF_2026",publication_uri="https://openaccess.thecvf.com/content/CVPR2026F/html/Li_EchoTrail-GUI_Building_Actionable_Memory_for_GUI_Agents_via_Critic-Guided_Self-Exploration_CVPRF_2026_paper.html",revision="CVPR Findings 2026 final proceedings paper")

SOURCES=MethodSourceRegistry(lanes=(PUBLICATION,))
__all__=["PUBLICATION","SOURCES"]
