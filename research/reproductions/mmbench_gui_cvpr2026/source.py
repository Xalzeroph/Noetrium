from __future__ import annotations
from research.reproductions.provenance import MethodSourceRegistry, PublicationSourceLane
PUBLICATION=PublicationSourceLane(lane_id="final_publication",venue="CVPR",year=2026,publication_id="Wang_MMBench_GUI_CVPR_2026",publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wang_MMBench-GUI_A_Unified_Hierarchical_Evaluation_Framework_for_Multi-Platform_GUI_Agents_CVPR_2026_paper.html",revision="CVPR 2026 final proceedings paper")
SOURCES=MethodSourceRegistry(lanes=(PUBLICATION,))
__all__=["PUBLICATION","SOURCES"]
