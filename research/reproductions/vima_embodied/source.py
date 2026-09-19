from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

VIMA_POLICY_AUDITED_COMMIT = "a16536f55780738ec2ce932f882f15bc011d7307"
VIMA_BENCH_AUDITED_COMMIT = "224c2d870d6063d90215201ba42d4211ddc957d7"

VIMA_ICML_2023 = PublicationSourceLane(
    lane_id="icml_2023_camera_ready",
    venue="ICML",
    year=2023,
    publication_id="vima-icml-2023",
    publication_uri="https://proceedings.mlr.press/v202/jiang23b.html",
    revision="ICML 2023 camera-ready paper",
)

VIMA_POLICY_EXECUTABLE = MethodSourceLane(
    lane_id="policy_camera_ready",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/vimalabs/VIMA",
    commit=VIMA_POLICY_AUDITED_COMMIT,
    artifacts=(
        "vima/policy/vima_policy.py",
        "vima/nn/action_decoder/action_decoder.py",
        "vima/nn/action_decoder/dists.py",
        "vima/nn/action_embd",
        "vima/nn/obj_encoder",
        "vima/nn/prompt_encoder",
        "vima/nn/seq_modeling",
        "scripts/example.py",
    ),
)

VIMA_BENCH_EXECUTABLE = MethodSourceLane(
    lane_id="benchmark_camera_ready",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/vimalabs/VIMABench",
    commit=VIMA_BENCH_AUDITED_COMMIT,
    artifacts=(
        "vima_bench",
        "vimasim",
        "scripts/oracle",
        "scripts/data_generation",
        "README.md",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(
        VIMA_ICML_2023,
        VIMA_POLICY_EXECUTABLE,
        VIMA_BENCH_EXECUTABLE,
    ),
)

__all__ = [
    "SOURCES",
    "VIMA_BENCH_AUDITED_COMMIT",
    "VIMA_BENCH_EXECUTABLE",
    "VIMA_ICML_2023",
    "VIMA_POLICY_AUDITED_COMMIT",
    "VIMA_POLICY_EXECUTABLE",
]
