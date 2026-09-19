from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

FSE_2025_PUBLICATION = PublicationSourceLane(
    lane_id="fse_2025_final",
    venue="FSE",
    year=2025,
    publication_id="10.1145/3715754",
    publication_uri=(
        "https://conf.researchr.org/details/fse-2025/"
        "fse-2025-research-papers/85/"
        "Demystifying-LLM-based-Software-Engineering-Agents"
    ),
    revision="FSE 2025 research paper",
)

AGENTLESS_V1_5 = MethodSourceLane(
    lane_id="agentless_v1_5",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/OpenAutoCoder/Agentless",
    commit="b150f28465a77a81a7f4776384957a4271f5bd69",
    artifacts=(
        "agentless/fl/localize.py",
        "agentless/repair/repair.py",
        "agentless/repair/rerank.py",
        "agentless/test/select_regression_tests.py",
        "agentless/test/generate_reproduction_tests.py",
        "agentless/test/run_tests.py",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(FSE_2025_PUBLICATION, AGENTLESS_V1_5),
)

__all__ = [
    "AGENTLESS_V1_5",
    "FSE_2025_PUBLICATION",
    "SOURCES",
]
