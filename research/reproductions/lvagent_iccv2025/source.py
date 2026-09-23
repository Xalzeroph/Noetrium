from __future__ import annotations

from research.reproductions.provenance import MethodSourceLane, MethodSourceLaneKind, MethodSourceRegistry, PublicationSourceLane

LVAGENT_PUBLICATION = PublicationSourceLane(
    lane_id="iccv_2025",
    venue="ICCV",
    year=2025,
    publication_id="lvagent-iccv-2025",
    publication_uri="https://openaccess.thecvf.com/content/ICCV2025/html/Chen_LVAgent_Long_Video_Understanding_by_Multi-Round_Dynamical_Collaboration_of_MLLM_ICCV_2025_paper.html",
    revision="ICCV 2025 proceedings publication",
)

LVAGENT_OFFICIAL_EXECUTABLE = MethodSourceLane(
    lane_id="official_executable",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/64327069/LVAgent",
    commit="659b9cb1cf41ddce15c7fe21a8a5d11abf93f147",
    artifacts=("README.md",),
)

SOURCES = MethodSourceRegistry(lanes=(LVAGENT_PUBLICATION, LVAGENT_OFFICIAL_EXECUTABLE))

__all__ = ["LVAGENT_PUBLICATION","SOURCES","LVAGENT_OFFICIAL_EXECUTABLE"]
