from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceRegistry,
    PublicationSourceLane,
)

SOURCE_ICLR_2023_PAPER = PublicationSourceLane(
    lane_id="iclr_2023_final",
    venue="ICLR",
    year=2023,
    publication_id="1PL1NIMMrw",
    publication_uri="https://openreview.net/forum?id=1PL1NIMMrw",
    revision="published conference paper",
)

SOURCES = MethodSourceRegistry(lanes=(SOURCE_ICLR_2023_PAPER,))

__all__ = ["SOURCE_ICLR_2023_PAPER", "SOURCES"]
