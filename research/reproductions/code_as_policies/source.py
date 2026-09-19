from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

CODE_AS_POLICIES_INITIAL_RELEASE_COMMIT = (
    "8ea35031973c001433944eef3bfa9587ce8e0f75"
)
CODE_AS_POLICIES_INTERACTIVE_RELEASE_COMMIT = (
    "d39dfbb5d1256cc930d3946a933aa5dc5d416ad5"
)
CODE_AS_POLICIES_AUDITED_COMMIT = (
    "71896d4b6816983672aa6999e2dc92a3cfe904e4"
)

CODE_AS_POLICIES_ICRA_2023 = PublicationSourceLane(
    lane_id="icra_2023",
    venue="ICRA",
    year=2023,
    publication_id="code-as-policies-icra-2023",
    publication_uri="https://arxiv.org/abs/2209.07753",
    revision="ICRA 2023 paper; paper-era public code released in 2022",
)

CODE_AS_POLICIES_METHOD_COLABS = MethodSourceLane(
    lane_id="official_method_colabs",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/google-research/google-research",
    commit=CODE_AS_POLICIES_INITIAL_RELEASE_COMMIT,
    artifacts=(
        "code_as_policies/LMP Examples.ipynb",
        "code_as_policies/Experiment_ HumanEval Benchmark.ipynb",
        "code_as_policies/Experiment_ Reactive Controllers on Toy Tasks.ipynb",
        "code_as_policies/Experiment_ Reasoning with Code vs Natural Language.ipynb",
        "code_as_policies/Experiment_ Robot Code-Gen Benchmark.ipynb",
        "code_as_policies/README.md",
    ),
)

CODE_AS_POLICIES_INTERACTIVE_DEMO = MethodSourceLane(
    lane_id="official_interactive_demo",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/google-research/google-research",
    commit=CODE_AS_POLICIES_INTERACTIVE_RELEASE_COMMIT,
    artifacts=(
        "code_as_policies/Interactive_Demo.ipynb",
        "code_as_policies/README.md",
    ),
)

CODE_AS_POLICIES_AUDIT_CUT = MethodSourceLane(
    lane_id="paper_era_audit_cut",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/google-research/google-research",
    commit=CODE_AS_POLICIES_AUDITED_COMMIT,
    artifacts=(
        "code_as_policies/LMP Examples.ipynb",
        "code_as_policies/Interactive_Demo.ipynb",
        "code_as_policies/Experiment_ Robot Code-Gen Benchmark.ipynb",
        "code_as_policies/README.md",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(
        CODE_AS_POLICIES_ICRA_2023,
        CODE_AS_POLICIES_METHOD_COLABS,
        CODE_AS_POLICIES_INTERACTIVE_DEMO,
        CODE_AS_POLICIES_AUDIT_CUT,
    ),
)

__all__ = [
    "CODE_AS_POLICIES_AUDITED_COMMIT",
    "CODE_AS_POLICIES_AUDIT_CUT",
    "CODE_AS_POLICIES_ICRA_2023",
    "CODE_AS_POLICIES_INITIAL_RELEASE_COMMIT",
    "CODE_AS_POLICIES_INTERACTIVE_DEMO",
    "CODE_AS_POLICIES_INTERACTIVE_RELEASE_COMMIT",
    "CODE_AS_POLICIES_METHOD_COLABS",
    "SOURCES",
]
