from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

SOURCE_NAACL_2024_PAPER = PublicationSourceLane(
    lane_id="naacl_2024_final",
    venue="NAACL",
    year=2024,
    publication_id="2024.naacl-long.347",
    publication_uri="https://aclanthology.org/2024.naacl-long.347/",
    revision="NAACL 2024 final",
)

OFFICIAL_STORM_WIKI = MethodSourceLane(
    lane_id="official_storm_wiki",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/stanford-oval/storm",
    commit="1f8ac2ddb4dd5f8cfcc250fdd3611c693098134b",
    artifacts=(
        "src/storm_wiki/engine.py",
        "src/storm_wiki/modules/knowledge_curation.py",
        "src/storm_wiki/modules/persona_generator.py",
        "src/storm_wiki/modules/outline_generation.py",
        "src/storm_wiki/modules/article_generation.py",
        "src/storm_wiki/modules/article_polish.py",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(SOURCE_NAACL_2024_PAPER, OFFICIAL_STORM_WIKI),
)

__all__ = [
    "SOURCES",
    "SOURCE_NAACL_2024_PAPER",
    "OFFICIAL_STORM_WIKI",
]
