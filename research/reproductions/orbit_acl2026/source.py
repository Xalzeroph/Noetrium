from __future__ import annotations
from noetrium_platform.research.provenance import MethodSourceLane, MethodSourceLaneKind, MethodSourceRegistry, PublicationSourceLane
PUBLICATION=PublicationSourceLane(lane_id="final_publication",venue="ACL",year=2026,publication_id="2026.acl-long.1822",publication_uri="https://aclanthology.org/2026.acl-long.1822/",revision="ACL 2026 final proceedings paper")

OFFICIAL_REPOSITORY_CUT=MethodSourceLane(
    lane_id="official_repository_cut",
    kind=MethodSourceLaneKind.OFFICIAL_ARTIFACT,
    repository="https://github.com/mail-taii/Reinforced-Reasoning-for-Embodied-Planning",
    commit="48802811cbf30a1071cac7f3227dccab258cc1fe",
    artifacts=("README.md",),
)

SOURCES=MethodSourceRegistry(lanes=(PUBLICATION, OFFICIAL_REPOSITORY_CUT,))
__all__=["PUBLICATION","SOURCES"]
