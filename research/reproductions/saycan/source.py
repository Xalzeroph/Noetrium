from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

SAYCAN_PAPER_CODE_COMMIT = "8c56e5dfc49613a57b80d6cfa2c9d6605cc08d10"

SAYCAN_CORL_2022 = PublicationSourceLane(
    lane_id="corl_2022_camera_ready",
    venue="CoRL",
    year=2022,
    publication_id="saycan-corl-2022",
    publication_uri="https://proceedings.mlr.press/v205/ichter23a.html",
    revision="CoRL 2022 / PMLR 205 camera-ready publication",
)

SAYCAN_OFFICIAL_NOTEBOOK = MethodSourceLane(
    lane_id="official_pick_place_notebook",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/google-research/google-research",
    commit=SAYCAN_PAPER_CODE_COMMIT,
    artifacts=(
        "saycan/README.md",
        "saycan/SayCan-Robot-Pick-Place.ipynb",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(
        SAYCAN_CORL_2022,
        SAYCAN_OFFICIAL_NOTEBOOK,
    ),
)

__all__ = [
    "SOURCES",
    "SAYCAN_CORL_2022",
    "SAYCAN_OFFICIAL_NOTEBOOK",
    "SAYCAN_PAPER_CODE_COMMIT",
]
