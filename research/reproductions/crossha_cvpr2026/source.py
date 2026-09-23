from __future__ import annotations
from research.reproductions.provenance import MethodSourceLane, MethodSourceLaneKind, MethodSourceRegistry, PublicationSourceLane
PUBLICATION=PublicationSourceLane(lane_id="final_publication",venue="CVPR",year=2026,publication_id="He_CrossHA_CVPR_2026",publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/He_Training_One_Model_to_Master_Cross-Level_Agentic_Actions_via_Reinforcement_CVPR_2026_paper.html",revision="CVPR 2026 final proceedings paper")
OFFICIAL_REPOSITORY_CUT=MethodSourceLane(lane_id="official_repository_cut",kind=MethodSourceLaneKind.OFFICIAL_ARTIFACT,repository="https://github.com/CraftJarvis/OpenHA",commit="606efc69e945bd02c700e584136bcc105d22f122",artifacts=("README.md",))
SOURCES=MethodSourceRegistry(lanes=(PUBLICATION,OFFICIAL_REPOSITORY_CUT))
__all__=["PUBLICATION","SOURCES"]
