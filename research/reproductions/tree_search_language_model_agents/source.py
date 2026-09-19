from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
SOURCE_OFFICIAL_SEARCH_AGENTS_REPO = MethodSourceLane(
    lane_id='official_search_agents_repo',
    kind=MethodSourceLaneKind('official_executable'),
    repository='https://github.com/kohjingyu/search-agents',
    commit='7c35ac9eb7fda663d821449efdfd44d360fd0e18',
    artifacts=('scripts/run_vwa_shopping_search.sh', 'run.py', 'agent/prompts/jsons/p_som_cot_id_actree_3s.json'),
)

SOURCES = MethodSourceRegistry(
    lanes=(SOURCE_OFFICIAL_SEARCH_AGENTS_REPO,),
)

__all__ = [
    "SOURCES",
    "SOURCE_OFFICIAL_SEARCH_AGENTS_REPO",
]
