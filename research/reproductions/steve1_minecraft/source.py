from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

STEVE1_OFFICIAL_REPOSITORY = "https://github.com/Shalev-Lifshitz/STEVE-1"
STEVE1_AUDITED_COMMIT = "874cf9b808c9dd0a5d4446ef2e008e3789c55c57"

STEVE1_NEURIPS_2023 = PublicationSourceLane(
    lane_id="neurips_2023",
    venue="NeurIPS",
    year=2023,
    publication_id="steve1-neurips-2023",
    publication_uri=(
        "https://proceedings.neurips.cc/paper_files/paper/2023/hash/"
        "dd03f856fc7f2efeec8b1c796284561d-Abstract-Conference.html"
    ),
    revision="NeurIPS 2023 Main Conference",
)

STEVE1_OFFICIAL_EXECUTABLE = MethodSourceLane(
    lane_id="official_paper_consistent",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository=STEVE1_OFFICIAL_REPOSITORY,
    commit=STEVE1_AUDITED_COMMIT,
    artifacts=(
        "steve1/config.py",
        "steve1/MineRLConditionalAgent.py",
        "steve1/embed_conditioned_policy.py",
        "steve1/run_agent/run_agent.py",
        "steve1/run_agent/programmatic_eval.py",
        "run_agent/1_gen_paper_videos.sh",
        "run_agent/2_gen_vid_for_text_prompt.sh",
        "train/3_train.sh",
        "train/4_train_prior.sh",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(STEVE1_NEURIPS_2023, STEVE1_OFFICIAL_EXECUTABLE),
)

__all__ = [
    "SOURCES",
    "STEVE1_AUDITED_COMMIT",
    "STEVE1_NEURIPS_2023",
    "STEVE1_OFFICIAL_EXECUTABLE",
    "STEVE1_OFFICIAL_REPOSITORY",
]
