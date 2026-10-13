from __future__ import annotations

from research.reproductions.provenance import MethodSourceLane, MethodSourceLaneKind, MethodSourceRegistry, PublicationSourceLane

WEBAGENT_R1_PUBLICATION = PublicationSourceLane(
    lane_id="emnlp_2025",
    venue="EMNLP",
    year=2025,
    publication_id="webagent-r1-emnlp-2025",
    publication_uri="https://aclanthology.org/2025.emnlp-main.401/",
    revision="EMNLP 2025 proceedings publication",
)

WEBAGENT_R1_OFFICIAL_EXECUTABLE = MethodSourceLane(
    lane_id="official_executable",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/weizhepei/WebAgent-R1",
    commit="354f5c18d4931941165ca3399b5a64e816b3295f",
    artifacts=("README.md",),
)

SOURCES = MethodSourceRegistry(lanes=(WEBAGENT_R1_PUBLICATION, WEBAGENT_R1_OFFICIAL_EXECUTABLE))

__all__ = ["WEBAGENT_R1_PUBLICATION","SOURCES","WEBAGENT_R1_OFFICIAL_EXECUTABLE"]
