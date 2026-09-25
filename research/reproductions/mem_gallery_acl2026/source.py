from __future__ import annotations

from research.reproductions.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

PUBLICATION = PublicationSourceLane(
    lane_id="final_publication",
    venue="ACL",
    year=2026,
    publication_id="2026.acl-long.1892",
    publication_uri="https://aclanthology.org/2026.acl-long.1892/",
    revision="ACL 2026 final proceedings paper",
)


OFFICIAL_REPOSITORY_CUT = MethodSourceLane(
    lane_id="official_repository_cut",
    kind=MethodSourceLaneKind.OFFICIAL_ARTIFACT,
    repository="https://github.com/YuanchenBei/Mem-Gallery",
    commit="a93959e1e978a6a7d77798ae92c2ffe41c538c62",
    artifacts=("README.md",),
)

SOURCES = MethodSourceRegistry(lanes=(PUBLICATION, OFFICIAL_REPOSITORY_CUT,))

__all__ = ["PUBLICATION", "SOURCES"]
