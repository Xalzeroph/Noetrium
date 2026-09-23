from __future__ import annotations

from research.reproductions.provenance import MethodSourceRegistry, PublicationSourceLane

ADAPTAGENT_PUBLICATION = PublicationSourceLane(
    lane_id="acl_2025",
    venue="ACL",
    year=2025,
    publication_id="adaptagent-acl-2025",
    publication_uri="https://aclanthology.org/2025.acl-long.1008/",
    revision="ACL 2025 proceedings publication",
)

SOURCES = MethodSourceRegistry(lanes=(ADAPTAGENT_PUBLICATION,))

__all__ = ["ADAPTAGENT_PUBLICATION","SOURCES"]
