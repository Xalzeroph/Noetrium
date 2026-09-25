from __future__ import annotations

from dataclasses import dataclass


AGENT_S3_REPOSITORY = "simular-ai/Agent-S"
AGENT_S3_RELEASE = "v0.3.2"
AGENT_S3_RELEASE_COMMIT = "2cb57fb5b5cc4798394fab85691d45b7a12391ba"


@dataclass(frozen=True, slots=True)
class AgentS3Fidelity:
    """Agent S3 semantics pinned to the official v0.3.2 source release."""

    repository: str = AGENT_S3_REPOSITORY
    release: str = AGENT_S3_RELEASE
    release_commit: str = AGENT_S3_RELEASE_COMMIT
    paper_arxiv: str = "2510.02250"
    agent_source: str = "gui_agents/s3/agents/agent_s.py"
    worker_source: str = "gui_agents/s3/agents/worker.py"
    code_agent_source: str = "gui_agents/s3/agents/code_agent.py"
    grounding_source: str = "gui_agents/s3/agents/grounding.py"
    hierarchy_enabled: bool = False
    default_max_trajectory_length: int = 8
    default_reflection_enabled: bool = True
    long_context_engine_types: tuple[str, ...] = ("anthropic", "openai", "gemini")
    code_agent_budget: int = 20
    code_agent_languages: tuple[str, ...] = ("python", "bash")
    benchmarks: tuple[str, ...] = ("OSWorld", "WindowsAgentArena", "AndroidWorld")
    behavior_best_of_n_is_separate: bool = True

    def __post_init__(self) -> None:
        if len(self.release_commit) != 40:
            raise ValueError("Agent S3 release commit must be a full git SHA")
        if self.hierarchy_enabled:
            raise ValueError("Agent S3 v0.3.x must not regain the S1/S2 hierarchy")
        if self.default_max_trajectory_length != 8:
            raise ValueError("Agent S3 default trajectory length drifted")
        if not self.default_reflection_enabled:
            raise ValueError("Agent S3 default reflection behavior drifted")
        if self.long_context_engine_types != ("anthropic", "openai", "gemini"):
            raise ValueError("Agent S3 long-context projection policy drifted")
        if self.code_agent_budget != 20:
            raise ValueError("Agent S3 code-agent budget drifted")
        if self.code_agent_languages != ("python", "bash"):
            raise ValueError("Agent S3 code-agent language surface drifted")
        if not self.behavior_best_of_n_is_separate:
            raise ValueError("Agent S3 base method must stay distinct from Behavior Best-of-N")


AGENT_S3_FIDELITY = AgentS3Fidelity()


__all__ = [
    "AGENT_S3_FIDELITY",
    "AGENT_S3_RELEASE",
    "AGENT_S3_RELEASE_COMMIT",
    "AGENT_S3_REPOSITORY",
    "AgentS3Fidelity",
]
