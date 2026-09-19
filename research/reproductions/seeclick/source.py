from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceRegistry,
    PublicationSourceLane,
)

SOURCE_ACL_2024_PAPER = PublicationSourceLane(
    lane_id="acl_2024_final",
    venue="ACL",
    year=2024,
    publication_id="2024.acl-long.505",
    publication_uri="https://aclanthology.org/2024.acl-long.505/",
    revision="ACL 2024 final",
)

SOURCES = MethodSourceRegistry(lanes=(SOURCE_ACL_2024_PAPER,))

__all__ = ["SOURCE_ACL_2024_PAPER", "SOURCES"]
