from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

JARVIS1_OFFICIAL_REPOSITORY = "https://github.com/CraftJarvis/JARVIS-1"
JARVIS1_PUBLIC_EXECUTABLE_COMMIT = "aa9bd97debee045cb35b37564c71dee4c465b9ad"

JARVIS1_TPAMI_2025 = PublicationSourceLane(
    lane_id="tpami_2025",
    venue="IEEE TPAMI",
    year=2025,
    publication_id="jarvis1-tpami-2025",
    publication_uri="https://ieeexplore.ieee.org/document/10778628/",
    revision=(
        "IEEE Transactions on Pattern Analysis and Machine Intelligence, "
        "47(3):1894-1907"
    ),
)

JARVIS1_PARTIAL_OFFICIAL_EXECUTABLE = MethodSourceLane(
    lane_id="partial_official_fixed_memory",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository=JARVIS1_OFFICIAL_REPOSITORY,
    commit=JARVIS1_PUBLIC_EXECUTABLE_COMMIT,
    artifacts=(
        "jarvis/assets/memory.json",
        "jarvis/assets/tasks.json",
        "jarvis/assets/skill.json",
        "jarvis/assembly/base.py",
        "jarvis/assembly/core.py",
        "jarvis/steveI/steveI_text.py",
        "jarvis/steveI/steveI_visual.py",
        "offline_evaluation.py",
        "README.md",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(
        JARVIS1_TPAMI_2025,
        JARVIS1_PARTIAL_OFFICIAL_EXECUTABLE,
    ),
)

__all__ = [
    "JARVIS1_OFFICIAL_REPOSITORY",
    "JARVIS1_PARTIAL_OFFICIAL_EXECUTABLE",
    "JARVIS1_PUBLIC_EXECUTABLE_COMMIT",
    "JARVIS1_TPAMI_2025",
    "SOURCES",
]
