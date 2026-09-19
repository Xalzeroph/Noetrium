from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

DEPS_RELEASE_COMMIT = "df7067614ed527a2b56262441472886f1eb628ca"
DEPS_REPLAN_SEMANTICS_COMMIT = "fa2278e523b85aede67a4225b2f0da2d187bc74b"

DEPS_NEURIPS_2023 = PublicationSourceLane(
    lane_id="neurips_2023_main",
    venue="NeurIPS",
    year=2023,
    publication_id="deps-minecraft-neurips-2023",
    publication_uri=(
        "https://proceedings.neurips.cc/paper_files/paper/2023/hash/"
        "6b8dfb8c0c12e6fafc6c256cb08a5ca7-Abstract-Conference.html"
    ),
    revision="NeurIPS 2023 main conference paper",
)

DEPS_OFFICIAL_EXECUTABLE = MethodSourceLane(
    lane_id="official_mc_planner_release",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/CraftJarvis/MC-Planner",
    commit=DEPS_RELEASE_COMMIT,
    artifacts=(
        "planner.py",
        "main.py",
        "selector.py",
        "controller.py",
        "configs",
        "data/task_prompt.txt",
        "data/deps_prompt.txt",
        "data/parse_prompt.txt",
        "data/goal_lib.json",
        "data/task_info.json",
    ),
)

DEPS_REPLAN_SEMANTICS = MethodSourceLane(
    lane_id="replan_semantics_fix",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/CraftJarvis/MC-Planner",
    commit=DEPS_REPLAN_SEMANTICS_COMMIT,
    artifacts=("planner.py", "main.py"),
)

SOURCES = MethodSourceRegistry(
    lanes=(
        DEPS_NEURIPS_2023,
        DEPS_OFFICIAL_EXECUTABLE,
        DEPS_REPLAN_SEMANTICS,
    ),
)

__all__ = [
    "DEPS_NEURIPS_2023",
    "DEPS_OFFICIAL_EXECUTABLE",
    "DEPS_RELEASE_COMMIT",
    "DEPS_REPLAN_SEMANTICS",
    "DEPS_REPLAN_SEMANTICS_COMMIT",
    "SOURCES",
]
