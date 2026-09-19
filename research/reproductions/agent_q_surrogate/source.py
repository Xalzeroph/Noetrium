from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
)
SOURCE_SENTIENT_OSS_SURROGATE = MethodSourceLane(
    lane_id='sentient_oss_surrogate',
    kind=MethodSourceLaneKind('surrogate'),
    repository='https://github.com/sentient-engineering/agent-q',
    commit='6050777f833f43c36421398cb2f524ea9709c839',
    artifacts=('README.md', 'agentq/core/mcts/browser_mcts.py', 'agentq/core/mcts/core/base.py', 'agentq/core/mcts/core/mcts.py', 'agentq/core/orchestrator/orchestrator.py', 'dpo_pairs.jsonl', 'test/tasks/webvoyager_test.json'),
)

SOURCES = MethodSourceRegistry(
    lanes=(SOURCE_SENTIENT_OSS_SURROGATE,),
)

__all__ = [
    "SOURCES",
    "SOURCE_SENTIENT_OSS_SURROGATE",
]
