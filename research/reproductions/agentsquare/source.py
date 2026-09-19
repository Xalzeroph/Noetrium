from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

AGENTSQUARE_ICLR_2025 = PublicationSourceLane(
    lane_id="iclr_2025_final",
    venue="ICLR",
    year=2025,
    publication_id="0ae94013da7cd459402fd77874e09ee3",
    publication_uri=(
        "https://proceedings.iclr.cc/paper_files/paper/2025/hash/"
        "0ae94013da7cd459402fd77874e09ee3-Abstract-Conference.html"
    ),
    revision="ICLR 2025 final paper",
)

AGENTSQUARE_LATER_OFFICIAL = MethodSourceLane(
    lane_id="later_official_search_implementation",
    kind=MethodSourceLaneKind.LATER_RELEASED_EXECUTABLE,
    repository="https://github.com/tsinghua-fib-lab/AgentSquare",
    commit="8f5b3fe5d8a32f9b59d20370823bef2a2c86928c",
    artifacts=(
        "search/agent_search.py",
        "search/module_evolution.py",
        "search/recombination.py",
        "search/module_predictor.py",
        "tasks/alfworld/agent.py",
        "tasks/alfworld/module_map.py",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(AGENTSQUARE_ICLR_2025, AGENTSQUARE_LATER_OFFICIAL),
)

__all__ = [
    "AGENTSQUARE_ICLR_2025",
    "AGENTSQUARE_LATER_OFFICIAL",
    "SOURCES",
]
