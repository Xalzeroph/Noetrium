from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

CHATDEV_V1_PUBLICATION = PublicationSourceLane(
    lane_id="acl_2024_publication",
    venue="ACL",
    year=2024,
    publication_id="2024.acl-long.810",
    publication_uri="https://aclanthology.org/2024.acl-long.810/",
    revision="ACL 2024 long paper",
)

CHATDEV_V1_OFFICIAL_EXECUTABLE = MethodSourceLane(
    lane_id="chatdev_v1_official_executable",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/OpenBMB/ChatDev",
    commit="acb93cf3d15cec5b9ee6eec0850ddd3932164329",
    artifacts=(
        "CompanyConfig/Default/ChatChainConfig.json",
        "CompanyConfig/Default/PhaseConfig.json",
        "CompanyConfig/Default/RoleConfig.json",
        "chatdev/chat_chain.py",
        "chatdev/composed_phase.py",
        "chatdev/phase.py",
        "requirements.txt",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(
        CHATDEV_V1_PUBLICATION,
        CHATDEV_V1_OFFICIAL_EXECUTABLE,
    ),
)

__all__ = [
    "CHATDEV_V1_OFFICIAL_EXECUTABLE",
    "CHATDEV_V1_PUBLICATION",
    "SOURCES",
]
