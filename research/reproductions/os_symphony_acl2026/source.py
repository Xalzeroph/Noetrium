from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

PUBLICATION = PublicationSourceLane(
    lane_id="final_publication",
    venue="ACL",
    year=2026,
    publication_id="2026.acl-long.1021",
    publication_uri="https://aclanthology.org/2026.acl-long.1021/",
    revision="ACL 2026 final proceedings paper",
)


OFFICIAL_REPOSITORY_CUT = MethodSourceLane(
    lane_id="official_repository_cut",
    kind=MethodSourceLaneKind.OFFICIAL_ARTIFACT,
    repository="https://github.com/OS-Copilot/OS-Symphony",
    commit="983d2f9f778cc4e19f9c6be7dc672a1245193ec0",
    artifacts=("README.md",),
)

SOURCES = MethodSourceRegistry(lanes=(PUBLICATION, OFFICIAL_REPOSITORY_CUT,))

__all__ = ["PUBLICATION", "SOURCES"]
