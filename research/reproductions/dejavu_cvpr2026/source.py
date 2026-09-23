from __future__ import annotations
from research.reproductions.provenance import MethodSourceRegistry, PublicationSourceLane
PUBLICATION=PublicationSourceLane(lane_id="final_publication",venue="CVPR",year=2026,publication_id="Wu_Dejavu_CVPR_2026",publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_Dejavu_Towards_Experience_Feedback_Learning_for_Embodied_Intelligence_CVPR_2026_paper.html",revision="CVPR 2026 final proceedings paper")
SOURCES=MethodSourceRegistry(lanes=(PUBLICATION,))
__all__=["PUBLICATION","SOURCES"]
