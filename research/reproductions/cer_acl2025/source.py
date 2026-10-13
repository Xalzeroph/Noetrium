from __future__ import annotations

from research.reproductions.provenance import MethodSourceRegistry, PublicationSourceLane

CER_PUBLICATION = PublicationSourceLane(
    lane_id="acl_2025",
    venue="ACL",
    year=2025,
    publication_id="cer-acl-2025",
    publication_uri="https://aclanthology.org/2025.acl-long.694/",
    revision="ACL 2025 proceedings publication",
)

SOURCES = MethodSourceRegistry(lanes=(CER_PUBLICATION,))

__all__ = ["CER_PUBLICATION","SOURCES"]
