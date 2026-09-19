from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

VOYAGER_TMLR_2024 = PublicationSourceLane(
    lane_id="tmlr_2024_final",
    venue="TMLR",
    year=2024,
    publication_id="wang2024tmlr-voyager",
    publication_uri="https://mlanthology.org/tmlr/2024/wang2024tmlr-voyager/",
    revision="TMLR 2024 final paper",
)

VOYAGER_PAPER_RELEASE = MethodSourceLane(
    lane_id="official_paper_release",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/MineDojo/Voyager",
    commit="edeee8383a22b96b54bff51c6cf809306a7b34a3",
    artifacts=(
        "voyager/voyager.py",
        "voyager/agents/action.py",
        "voyager/agents/critic.py",
        "voyager/agents/curriculum.py",
        "voyager/agents/skill.py",
        "voyager/env",
        "voyager/prompts",
        "voyager/control_primitives",
        "skill_library/README.md",
    ),
)

VOYAGER_POST_RELEASE_COMPATIBILITY = MethodSourceLane(
    lane_id="post_release_compatibility",
    kind=MethodSourceLaneKind.LATER_RELEASED_EXECUTABLE,
    repository="https://github.com/MineDojo/Voyager",
    commit="55e45a880755d0c8c66ca7fb5fe7962ac8974f89",
    artifacts=(
        "voyager/voyager.py",
        "voyager/agents/action.py",
        "voyager/agents/critic.py",
        "voyager/agents/curriculum.py",
        "voyager/agents/skill.py",
        "voyager/env/mineflayer/package.json",
        "requirements.txt",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(
        VOYAGER_TMLR_2024,
        VOYAGER_PAPER_RELEASE,
        VOYAGER_POST_RELEASE_COMPATIBILITY,
    ),
)

__all__ = [
    "SOURCES",
    "VOYAGER_PAPER_RELEASE",
    "VOYAGER_POST_RELEASE_COMPATIBILITY",
    "VOYAGER_TMLR_2024",
]
