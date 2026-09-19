from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

FLOW_ICLR_2025 = PublicationSourceLane(
    lane_id="iclr_2025_final",
    venue="ICLR",
    year=2025,
    publication_id="ba84da6921f3040b74ee163aa7451f53",
    publication_uri=(
        "https://proceedings.iclr.cc/paper_files/paper/2025/hash/"
        "ba84da6921f3040b74ee163aa7451f53-Abstract-Conference.html"
    ),
    revision="ICLR 2025 conference publication",
)

FLOW_LATER_OFFICIAL = MethodSourceLane(
    lane_id="later_official_flow_implementation",
    kind=MethodSourceLaneKind.LATER_RELEASED_EXECUTABLE,
    repository="https://github.com/tmllab/2025_ICLR_FLOW",
    commit="1bbfe1e699e6f35d5d422306c9a5bd637da84759",
    artifacts=(
        "flow.py",
        "workflow.py",
        "workflowManager.py",
        "runner.py",
        "taskexecuter.py",
        "autovalidator.py",
        "pythonvalidator.py",
        "textvalidator.py",
        "main.py",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(FLOW_ICLR_2025, FLOW_LATER_OFFICIAL),
)

__all__ = [
    "FLOW_ICLR_2025",
    "FLOW_LATER_OFFICIAL",
    "SOURCES",
]
