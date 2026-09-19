from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

OFFICIAL_WEBVOYAGER_V1 = MethodSourceLane(
    lane_id="official_webvoyager_v1",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/MinorJerry/WebVoyager",
    commit="091544539eba485dbd74ef3742011ddeede37336",
    artifacts=(
        "run.py",
        "run.sh",
        "prompts.py",
        "utils.py",
        "data/WebVoyager_data.jsonl",
    ),
)

ACL_2024_PUBLICATION = PublicationSourceLane(
    lane_id="acl_2024_final",
    venue="ACL",
    year=2024,
    publication_id="2024.acl-long.371",
    publication_uri="https://aclanthology.org/2024.acl-long.371/",
    revision="ACL 2024 long paper",
)

SOURCES = MethodSourceRegistry(
    lanes=(ACL_2024_PUBLICATION, OFFICIAL_WEBVOYAGER_V1),
)

__all__ = [
    "ACL_2024_PUBLICATION",
    "OFFICIAL_WEBVOYAGER_V1",
    "SOURCES",
]
