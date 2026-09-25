from __future__ import annotations
from research.reproductions.provenance import MethodSourceRegistry, PublicationSourceLane
PUBLICATION=PublicationSourceLane(lane_id="final_publication",venue="CVPR",year=2026,publication_id="Wu_ReFAct_CVPR_2026",publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_ReFAct_Empowering_Multimodal_Web_Agents_with_Visual_and_Context_Focusing_CVPR_2026_paper.html",revision="CVPR 2026 final proceedings paper")
SOURCES=MethodSourceRegistry(lanes=(PUBLICATION,))
__all__=["PUBLICATION","SOURCES"]
