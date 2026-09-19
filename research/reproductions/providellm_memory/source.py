from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)


PROVIDELLM_PAPER_ERA_COMMIT = "bd097cc0ee1c9a7eebe9ad767430c55456398a8d"

PROVIDELLM_ICCV_2025 = PublicationSourceLane(
    lane_id="iccv_2025_camera_ready",
    venue="ICCV",
    year=2025,
    publication_id="providellm-iccv-2025",
    publication_uri=(
        "https://openaccess.thecvf.com/content/ICCV2025/html/"
        "Chatterjee_Streaming_VideoLLMs_for_Real-Time_Procedural_"
        "Video_Understanding_ICCV_2025_paper.html"
    ),
    revision="ICCV 2025 camera-ready paper",
)

PROVIDELLM_INITIAL_OFFICIAL_RELEASE = MethodSourceLane(
    lane_id="initial_official_release",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/dibschat/ProVideLLM",
    commit=PROVIDELLM_PAPER_ERA_COMMIT,
    artifacts=(
        "models/arguments_live.py",
        "models/modeling_live.py",
        "models/live_llama/modeling_live_llama.py",
        "models/live_llama/connector.py",
        "README.md",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(PROVIDELLM_ICCV_2025, PROVIDELLM_INITIAL_OFFICIAL_RELEASE),
)


__all__ = [
    "PROVIDELLM_ICCV_2025",
    "PROVIDELLM_INITIAL_OFFICIAL_RELEASE",
    "PROVIDELLM_PAPER_ERA_COMMIT",
    "SOURCES",
]
