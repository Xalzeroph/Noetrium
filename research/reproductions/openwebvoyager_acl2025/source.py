from __future__ import annotations

from research.reproductions.provenance import MethodSourceRegistry, PublicationSourceLane

OPENWEBVOYAGER_PUBLICATION = PublicationSourceLane(
    lane_id="acl_2025",
    venue="ACL",
    year=2025,
    publication_id="openwebvoyager-acl-2025",
    publication_uri="https://aclanthology.org/2025.acl-long.1336/",
    revision="ACL 2025 proceedings publication",
)

SOURCES = MethodSourceRegistry(lanes=(OPENWEBVOYAGER_PUBLICATION,))

__all__ = ["OPENWEBVOYAGER_PUBLICATION","SOURCES"]
