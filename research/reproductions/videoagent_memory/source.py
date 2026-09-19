from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

VIDEOAGENT_INITIAL_COMMIT = "43c0fa82880e36ae5e01474276040e5379443ec1"
VIDEOAGENT_PROMPT_FIX_COMMIT = "df8d6bda5a8860d5932d664e4a4fbd0ab794dfdb"
VIDEOAGENT_AUDITED_COMMIT = "02dbfd47732910a2e7348e47f695585d05178aba"
VIDEOAGENT_MULTIPLE_CHOICE_EXAMPLE_COMMIT = (
    "21e4eb745b5ff4341f45170ddca02e0561ed088f"
)

VIDEOAGENT_ECCV_2024 = PublicationSourceLane(
    lane_id="eccv_2024_final",
    venue="ECCV",
    year=2024,
    publication_id="videoagent-memory-eccv-2024",
    publication_uri=(
        "https://www.ecva.net/papers/eccv_2024/papers_ECCV/"
        "html/3241_ECCV_2024_paper.php"
    ),
    revision="ECCV 2024 final paper",
)

VIDEOAGENT_INITIAL_EXECUTABLE = MethodSourceLane(
    lane_id="initial_public_executable",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/YueFan1014/VideoAgent",
    commit=VIDEOAGENT_INITIAL_COMMIT,
    artifacts=(
        "main.py",
        "tools.py",
        "database.py",
        "segment_feature.py",
        "tracking.py",
        "reid.py",
        "prompts/prompt.txt",
        "prompts/database_query_prompt.txt",
    ),
)

VIDEOAGENT_PAPER_ERA_EXECUTABLE = MethodSourceLane(
    lane_id="paper_era_corrected_executable",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/YueFan1014/VideoAgent",
    commit=VIDEOAGENT_AUDITED_COMMIT,
    artifacts=(
        "main.py",
        "tools.py",
        "database.py",
        "segment_feature.py",
        "tracking.py",
        "reid.py",
        "config/default.yaml",
        "prompts/prompt.txt",
        "prompts/database_query_prompt.txt",
    ),
)

VIDEOAGENT_POST_PAPER_EXAMPLE = MethodSourceLane(
    lane_id="post_paper_multiple_choice_example",
    kind=MethodSourceLaneKind.LATER_RELEASED_EXECUTABLE,
    repository="https://github.com/YueFan1014/VideoAgent",
    commit=VIDEOAGENT_MULTIPLE_CHOICE_EXAMPLE_COMMIT,
    artifacts=("inference.py",),
)

SOURCES = MethodSourceRegistry(
    lanes=(
        VIDEOAGENT_ECCV_2024,
        VIDEOAGENT_INITIAL_EXECUTABLE,
        VIDEOAGENT_PAPER_ERA_EXECUTABLE,
        VIDEOAGENT_POST_PAPER_EXAMPLE,
    ),
)

__all__ = [
    "SOURCES",
    "VIDEOAGENT_AUDITED_COMMIT",
    "VIDEOAGENT_ECCV_2024",
    "VIDEOAGENT_INITIAL_COMMIT",
    "VIDEOAGENT_INITIAL_EXECUTABLE",
    "VIDEOAGENT_MULTIPLE_CHOICE_EXAMPLE_COMMIT",
    "VIDEOAGENT_PAPER_ERA_EXECUTABLE",
    "VIDEOAGENT_POST_PAPER_EXAMPLE",
    "VIDEOAGENT_PROMPT_FIX_COMMIT",
]
