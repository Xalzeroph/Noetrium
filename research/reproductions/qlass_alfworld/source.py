from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
SOURCE_PAPER_ERA_REPOSITORY_STATE = MethodSourceLane(
    lane_id='paper_era_repository_state',
    kind=MethodSourceLaneKind('paper_provenance'),
    repository='https://github.com/Rafa-zy/QLASS',
    commit='65a291d3964a7f14a34cc274a28ca31636405334',
    artifacts=('README.md',),
)

SOURCE_LATER_RELEASED_QLASS_CODE = MethodSourceLane(
    lane_id='later_released_qlass_code',
    kind=MethodSourceLaneKind('later_released_executable'),
    repository='https://github.com/Rafa-zy/QLASS',
    commit='df8e6a3b840d1ea994114f13fc2d5ccd63b7a8e9',
    artifacts=('qlass/scripts/eval_q_wo_perturb_7b_alfworld.sh', 'qlass/q_guided_inference.py', 'data/q_guided_inference_wo_perturbation.py', 'eval_agent/tasks/alfworld.py'),
)

SOURCES = MethodSourceRegistry(
    lanes=(SOURCE_PAPER_ERA_REPOSITORY_STATE, SOURCE_LATER_RELEASED_QLASS_CODE,),
)

__all__ = [
    "SOURCES",
    "SOURCE_PAPER_ERA_REPOSITORY_STATE",
    "SOURCE_LATER_RELEASED_QLASS_CODE",
]
