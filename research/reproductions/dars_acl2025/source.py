from __future__ import annotations

from noetrium_platform.research.provenance import MethodSourceRegistry, PublicationSourceLane

DARS_PUBLICATION = PublicationSourceLane(
    lane_id="acl_2025",
    venue="ACL",
    year=2025,
    publication_id="dars-acl-2025",
    publication_uri="https://aclanthology.org/2025.acl-long.973/",
    revision="ACL 2025 proceedings publication",
)

SOURCES = MethodSourceRegistry(lanes=(DARS_PUBLICATION,))

__all__ = ["DARS_PUBLICATION","SOURCES"]
