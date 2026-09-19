from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)


MINEDOJO_AUDITED_COMMIT = "1fc46f58aaeed5eb8018abf030c95a13d41ab4a4"
MINECLIP_AUDITED_COMMIT = "5ec098c1660da44933ae9a221ea3ee180f973e0d"


MINEDOJO_NEURIPS_2022 = PublicationSourceLane(
    lane_id="neurips_2022_datasets_benchmarks",
    venue="NeurIPS",
    year=2022,
    publication_id="minedojo-neurips-2022",
    publication_uri=(
        "https://proceedings.neurips.cc/paper_files/paper/2022/hash/"
        "74a67268c5cc5910f64938cac4526a90-Abstract.html"
    ),
    revision="NeurIPS 2022 Datasets and Benchmarks Track",
)


MINEDOJO_EXECUTABLE = MethodSourceLane(
    lane_id="paper_consistent_benchmark_release",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/MineDojo/MineDojo",
    commit=MINEDOJO_AUDITED_COMMIT,
    artifacts=(
        "minedojo/tasks",
        "minedojo/sim",
        "minedojo/tasks/description_files/tasks_suite.yaml",
        "README.md",
    ),
)


MINECLIP_EXECUTABLE = MethodSourceLane(
    lane_id="mineclip_pretrained_release",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/MineDojo/MineCLIP",
    commit=MINECLIP_AUDITED_COMMIT,
    artifacts=(
        "mineclip/mineclip",
        "mineclip/mineagent",
        "mineclip/dense_reward",
        "main/mineclip",
        "README.md",
    ),
)


SOURCES = MethodSourceRegistry(
    lanes=(
        MINEDOJO_NEURIPS_2022,
        MINEDOJO_EXECUTABLE,
        MINECLIP_EXECUTABLE,
    ),
)


__all__ = [
    "MINECLIP_AUDITED_COMMIT",
    "MINECLIP_EXECUTABLE",
    "MINEDOJO_AUDITED_COMMIT",
    "MINEDOJO_EXECUTABLE",
    "MINEDOJO_NEURIPS_2022",
    "SOURCES",
]
