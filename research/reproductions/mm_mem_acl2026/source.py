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
    publication_id="2026.acl-long.533",
    publication_uri="https://aclanthology.org/2026.acl-long.533/",
    revision="ACL 2026 final proceedings paper",
)


OFFICIAL_REPOSITORY_CUT = MethodSourceLane(
    lane_id="official_repository_cut",
    kind=MethodSourceLaneKind.OFFICIAL_ARTIFACT,
    repository="https://github.com/EliSpectre/MM-Mem",
    commit="7a5e214c14dd5d9c4bb9e2fca7ae12948d49b4e8",
    artifacts=("README.md",),
)

SOURCES = MethodSourceRegistry(lanes=(PUBLICATION, OFFICIAL_REPOSITORY_CUT,))

__all__ = ["PUBLICATION", "SOURCES"]
