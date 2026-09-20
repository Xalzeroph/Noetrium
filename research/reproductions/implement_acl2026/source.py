from __future__ import annotations
from noetrium_platform.research.provenance import MethodSourceRegistry, PublicationSourceLane
PUBLICATION=PublicationSourceLane(lane_id="final_publication",venue="ACL",year=2026,publication_id="2026.acl-long.827",publication_uri="https://aclanthology.org/2026.acl-long.827/",revision="ACL 2026 final proceedings paper")

SOURCES=MethodSourceRegistry(lanes=(PUBLICATION,))
__all__=["PUBLICATION","SOURCES"]
