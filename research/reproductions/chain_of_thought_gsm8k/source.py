from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceRegistry,
    PublicationSourceLane,
)

SOURCE_NEURIPS_2022_PAPER = PublicationSourceLane(
    lane_id="neurips_2022_final",
    venue="NeurIPS",
    year=2022,
    publication_id="9d5609613524ecf4f15af0f7b31abca4",
    publication_uri=(
        "https://proceedings.neurips.cc/paper_files/paper/2022/hash/"
        "9d5609613524ecf4f15af0f7b31abca4-Abstract-Conference.html"
    ),
    revision="final conference version",
)

SOURCES = MethodSourceRegistry(lanes=(SOURCE_NEURIPS_2022_PAPER,))

__all__ = ["SOURCE_NEURIPS_2022_PAPER", "SOURCES"]
