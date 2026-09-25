from __future__ import annotations
from research.reproductions.provenance import MethodSourceLane, MethodSourceLaneKind, MethodSourceRegistry, PublicationSourceLane
PUBLICATION=PublicationSourceLane(lane_id="final_publication",venue="CVPR",year=2026,publication_id="Shao_HATS_CVPR_2026",publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Shao_HATS_Hardness-Aware_Trajectory_Synthesis_for_GUI_Agents_CVPR_2026_paper.html",revision="CVPR 2026 final proceedings paper")
OFFICIAL_REPOSITORY_CUT=MethodSourceLane(lane_id="official_repository_cut",kind=MethodSourceLaneKind.OFFICIAL_ARTIFACT,repository="https://github.com/JiuTian-VL/HATS",commit="8840bd1b7c28c0d04a2733e67fd69ed09f406278",artifacts=("README.md",))
SOURCES=MethodSourceRegistry(lanes=(PUBLICATION,OFFICIAL_REPOSITORY_CUT))
__all__=["PUBLICATION","SOURCES"]
