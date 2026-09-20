from __future__ import annotations
from noetrium_platform.research.provenance import MethodSourceLane, MethodSourceLaneKind, MethodSourceRegistry, PublicationSourceLane
PUBLICATION=PublicationSourceLane(lane_id="final_publication",venue="CVPR",year=2026,publication_id="Deng_CES_CVPR_2026",publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Deng_Training_High-Level_Schedulers_with_Execution-Feedback_Reinforcement_Learning_for_Long-Horizon_GUI_CVPR_2026_paper.html",revision="CVPR 2026 final proceedings paper")
OFFICIAL_REPOSITORY_CUT=MethodSourceLane(lane_id="official_repository_cut",kind=MethodSourceLaneKind.OFFICIAL_ARTIFACT,repository="https://github.com/hehehahi4/CES",commit="bf54b363eb769b957d6f80459fd0c0aadbbed44e",artifacts=("README.md",))
SOURCES=MethodSourceRegistry(lanes=(PUBLICATION,OFFICIAL_REPOSITORY_CUT))
__all__=["PUBLICATION","SOURCES"]
