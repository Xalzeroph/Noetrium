from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceRegistry,
    PublicationSourceLane,
)

SOURCE_NEURIPS_2023_PAPER = PublicationSourceLane(
    lane_id="neurips_2023_final",
    venue="NeurIPS",
    year=2023,
    publication_id="d842425e4bf79ba039352da0f658a906",
    publication_uri=(
        "https://proceedings.neurips.cc/paper/2023/hash/"
        "d842425e4bf79ba039352da0f658a906-Abstract-Conference.html"
    ),
    revision="final conference version",
)

SOURCES = MethodSourceRegistry(lanes=(SOURCE_NEURIPS_2023_PAPER,))

__all__ = ["SOURCE_NEURIPS_2023_PAPER", "SOURCES"]
