from __future__ import annotations

from research.reproductions.provenance import MethodSourceRegistry, PublicationSourceLane

R2D2_PUBLICATION = PublicationSourceLane(
    lane_id="acl_2025",
    venue="ACL",
    year=2025,
    publication_id="r2d2-acl-2025",
    publication_uri="https://aclanthology.org/2025.acl-long.1464/",
    revision="ACL 2025 proceedings publication",
)

SOURCES = MethodSourceRegistry(lanes=(R2D2_PUBLICATION,))

__all__ = ["R2D2_PUBLICATION","SOURCES"]
