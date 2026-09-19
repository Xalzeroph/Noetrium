from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)


OPTIMUS1_PAPER_ERA_COMMIT = "e789c58f53a4f831d67c4d6aaa008dbfd198a229"

OPTIMUS1_NEURIPS_2024 = PublicationSourceLane(
    lane_id="neurips_2024_main",
    venue="NeurIPS",
    year=2024,
    publication_id="optimus1-neurips-2024",
    publication_uri=(
        "https://proceedings.neurips.cc/paper_files/paper/2024/hash/"
        "5949a8750a110ce1f0631b1776c500a2-Abstract-Conference.html"
    ),
    revision="NeurIPS 2024 main conference paper",
)

OPTIMUS1_OFFICIAL_EXECUTABLE = MethodSourceLane(
    lane_id="official_code_release_2024_10_21",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/iLearn-Lab/NeurIPS24-Optimus-1",
    commit=OPTIMUS1_PAPER_ERA_COMMIT,
    artifacts=(
        "src/optimus1/main.py",
        "src/optimus1/memories/memory.py",
        "src/optimus1/memories/graph.py",
        "src/optimus1/models/gpt4_planning.py",
        "src/optimus1/models/steve_action_model.py",
        "src/optimus1/conf/evaluate.yaml",
        "src/optimus1/conf/benchmark",
        "scripts/diamond.sh",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(OPTIMUS1_NEURIPS_2024, OPTIMUS1_OFFICIAL_EXECUTABLE),
)


__all__ = [
    "OPTIMUS1_NEURIPS_2024",
    "OPTIMUS1_OFFICIAL_EXECUTABLE",
    "OPTIMUS1_PAPER_ERA_COMMIT",
    "SOURCES",
]
