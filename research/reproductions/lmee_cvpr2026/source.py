from __future__ import annotations
from noetrium_platform.research.provenance import MethodSourceLane, MethodSourceLaneKind, MethodSourceRegistry, PublicationSourceLane
PUBLICATION=PublicationSourceLane(lane_id="final_publication",venue="CVPR",year=2026,publication_id="Wang_Explore_with_Long-term_Memory_CVPR_2026",publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wang_Explore_with_Long-term_Memory_A_Benchmark_and_Multimodal_LLM-based_Reinforcement_CVPR_2026_paper.html",revision="CVPR 2026 final proceedings paper")
OFFICIAL_REPOSITORY_CUT=MethodSourceLane(lane_id="official_repository_cut",kind=MethodSourceLaneKind.OFFICIAL_ARTIFACT,repository="https://github.com/wangsen99/LMEE",commit="44b3d99af3f3b698566c1a76f69b73c36a4a4cdd",artifacts=("README.md",))
SOURCES=MethodSourceRegistry(lanes=(PUBLICATION,OFFICIAL_REPOSITORY_CUT))
__all__=["PUBLICATION","SOURCES"]
