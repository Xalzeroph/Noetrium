from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Protocol, runtime_checkable


class ToolLLMObservationStatus(IntEnum):
    """Paper-era ToolBench RapidAPI observation codes."""

    OK = 0
    HALLUCINATED_FUNCTION = 1
    INVALID_INPUT = 2
    GIVE_ANSWER = 3
    GIVE_UP_AND_RESTART = 4
    TIMEOUT = 5
    NOT_FOUND = 6
    UNSUBSCRIBED = 7
    UNAUTHORIZED = 8
    TOO_MANY_REQUESTS = 9
    RATE_LIMIT = 10
    TOOL_ERROR = 11
    REQUEST_ERROR = 12


class ToolLLMDFSDTNodeKind(StrEnum):
    THOUGHT = "Thought"
    ACTION = "Action"
    ACTION_INPUT = "Action Input"


@dataclass(frozen=True, slots=True)
class ToolLLMDFSDTCandidate:
    """One model expansion, matching ToolBench's optional content/function_call pair."""

    thought: str = ""
    action_name: str | None = None
    action_input: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.thought, str):
            raise TypeError("ToolLLM candidate thought must be text")
        if self.action_name is not None and (
            not isinstance(self.action_name, str) or not self.action_name.strip()
        ):
            raise ValueError("ToolLLM action_name must be non-empty when provided")
        if not isinstance(self.action_input, str):
            raise TypeError("ToolLLM action_input must be text")
        if self.action_name is None and self.action_input:
            raise ValueError("ToolLLM action_input requires an action_name")
        if not self.thought and self.action_name is None:
            raise ValueError("ToolLLM candidate must contain thought or action")


@dataclass(frozen=True, slots=True)
class ToolLLMToolObservation:
    content: str
    status: ToolLLMObservationStatus

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise TypeError("ToolLLM observation content must be text")
        if not isinstance(self.status, ToolLLMObservationStatus):
            raise TypeError("ToolLLM observation status must be typed")


@dataclass(frozen=True, slots=True)
class ToolLLMDFSDTTraceNode:
    kind: ToolLLMDFSDTNodeKind
    content: str
    observation: str = ""
    observation_status: ToolLLMObservationStatus | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ToolLLMDFSDTNodeKind):
            raise TypeError("ToolLLM trace node kind must be typed")
        if not isinstance(self.content, str):
            raise TypeError("ToolLLM trace node content must be text")
        if not isinstance(self.observation, str):
            raise TypeError("ToolLLM trace node observation must be text")
        if self.kind is ToolLLMDFSDTNodeKind.ACTION_INPUT:
            if self.observation_status is None:
                raise ValueError("ToolLLM Action Input node requires observation status")
        elif self.observation or self.observation_status is not None:
            raise ValueError("only ToolLLM Action Input nodes may own observations")


@dataclass(frozen=True, slots=True)
class ToolLLMDFSDTTrajectory:
    nodes: tuple[ToolLLMDFSDTTraceNode, ...] = ()

    @property
    def reasoning_steps(self) -> int:
        return sum(
            node.kind is ToolLLMDFSDTNodeKind.ACTION_INPUT
            for node in self.nodes
        )

    @property
    def terminal_status(self) -> ToolLLMObservationStatus | None:
        if not self.nodes:
            return None
        last = self.nodes[-1]
        return last.observation_status if last.kind is ToolLLMDFSDTNodeKind.ACTION_INPUT else None

    def append_candidate(
        self,
        candidate: ToolLLMDFSDTCandidate,
        observation: ToolLLMToolObservation | None,
    ) -> ToolLLMDFSDTTrajectory:
        nodes = list(self.nodes)
        if candidate.thought:
            nodes.append(ToolLLMDFSDTTraceNode(ToolLLMDFSDTNodeKind.THOUGHT, candidate.thought))
        if candidate.action_name is not None:
            if observation is None:
                raise ValueError("ToolLLM action candidate requires an observation")
            nodes.append(ToolLLMDFSDTTraceNode(ToolLLMDFSDTNodeKind.ACTION, candidate.action_name))
            nodes.append(
                ToolLLMDFSDTTraceNode(
                    ToolLLMDFSDTNodeKind.ACTION_INPUT,
                    candidate.action_input,
                    observation=observation.content,
                    observation_status=observation.status,
                )
            )
        elif observation is not None:
            raise ValueError("ToolLLM thought-only candidate cannot own an observation")
        return ToolLLMDFSDTTrajectory(tuple(nodes))


@runtime_checkable
class ToolLLMBranchEnvironment(Protocol):
    """Branch-local environment view; platform/environment remains source authority."""

    def fork(self) -> ToolLLMBranchEnvironment: ...

    def step(self, action_name: str, action_input: str) -> ToolLLMToolObservation: ...


@runtime_checkable
class ToolLLMDFSDTGeneratorPort(Protocol):
    def generate(
        self,
        trajectory: ToolLLMDFSDTTrajectory,
        previous_siblings: tuple[ToolLLMDFSDTTrajectory, ...],
    ) -> ToolLLMDFSDTCandidate: ...


@dataclass(frozen=True, slots=True)
class ToolLLMDFSDTRankResult:
    scores: tuple[float, ...]
    query_count: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.scores, tuple) or any(
            not isinstance(score, (int, float)) or isinstance(score, bool)
            for score in self.scores
        ):
            raise TypeError("ToolLLM rank scores must be numeric tuple")
        if type(self.query_count) is not int or self.query_count < 0:
            raise ValueError("ToolLLM rank query_count must be non-negative")


@runtime_checkable
class ToolLLMDFSDTRankerPort(Protocol):
    def rank(
        self,
        parent: ToolLLMDFSDTTrajectory,
        candidates: tuple[ToolLLMDFSDTTrajectory, ...],
    ) -> ToolLLMDFSDTRankResult: ...


@dataclass(frozen=True, slots=True)
class ToolLLMDFSDTConfig:
    max_reasoning_steps: int
    tree_beam_size: int
    max_query_count: int
    answer_count: int = 1
    with_filter: bool = False
    final_answer_back_length: int = 2
    prune_back_length: int = 2

    def __post_init__(self) -> None:
        for name in (
            "max_reasoning_steps",
            "tree_beam_size",
            "max_query_count",
            "answer_count",
            "final_answer_back_length",
            "prune_back_length",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"ToolLLM {name} must be positive")
        if type(self.with_filter) is not bool:
            raise TypeError("ToolLLM with_filter must be bool")


@dataclass(frozen=True, slots=True)
class ToolLLMDFSDTSearchResult:
    terminal: tuple[ToolLLMDFSDTTrajectory, ...]
    give_up: tuple[ToolLLMDFSDTTrajectory, ...]
    explored: tuple[ToolLLMDFSDTTrajectory, ...]
    query_count: int
    budget_exhausted: bool

    @property
    def solved(self) -> bool:
        return bool(self.terminal)


class ToolLLMDFSDTSearch:
    """Downstream reproduction of ToolBench's paper-era DFSDT control semantics.

    Search/backtracking/diversity are method policy. Environment truth and tool
    effects remain outside this object and are accessed only through a branch view.
    """

    def __init__(
        self,
        generator: ToolLLMDFSDTGeneratorPort,
        config: ToolLLMDFSDTConfig,
        *,
        ranker: ToolLLMDFSDTRankerPort | None = None,
    ) -> None:
        if not isinstance(config, ToolLLMDFSDTConfig):
            raise TypeError("ToolLLM DFSDT config must be typed")
        if not callable(getattr(generator, "generate", None)):
            raise TypeError("ToolLLM DFSDT generator must implement generate()")
        if config.with_filter and not callable(getattr(ranker, "rank", None)):
            raise TypeError("filtered ToolLLM DFS requires a ranker")
        self._generator = generator
        self._config = config
        self._ranker = ranker
        self._query_count = 0
        self._budget_exhausted = False
        self._terminal: list[ToolLLMDFSDTTrajectory] = []
        self._give_up: list[ToolLLMDFSDTTrajectory] = []
        self._explored: list[ToolLLMDFSDTTrajectory] = []

    def run(self, environment: ToolLLMBranchEnvironment) -> ToolLLMDFSDTSearchResult:
        if not callable(getattr(environment, "fork", None)) or not callable(
            getattr(environment, "step", None)
        ):
            raise TypeError("ToolLLM DFSDT environment must implement fork() and step()")
        self._query_count = 0
        self._budget_exhausted = False
        self._terminal = []
        self._give_up = []
        self._explored = []
        self._dfs(ToolLLMDFSDTTrajectory(), environment)
        return ToolLLMDFSDTSearchResult(
            terminal=tuple(self._terminal),
            give_up=tuple(self._give_up),
            explored=tuple(self._explored),
            query_count=self._query_count,
            budget_exhausted=self._budget_exhausted,
        )

    def _dfs(
        self,
        parent: ToolLLMDFSDTTrajectory,
        environment: ToolLLMBranchEnvironment,
    ) -> int:
        config = self._config
        if (
            parent.reasoning_steps >= config.max_reasoning_steps
            or len(self._terminal) >= config.answer_count
            or self._budget_exhausted
        ):
            return 1

        siblings: list[ToolLLMDFSDTTrajectory] = []
        branch_rows: list[tuple[ToolLLMDFSDTTrajectory, ToolLLMBranchEnvironment]] = []
        for _ in range(config.tree_beam_size):
            candidate = self._generator.generate(parent, tuple(siblings))
            self._query_count += 1
            # Paper code checks the query budget immediately after the model call;
            # the response that reaches the limit is not executed.
            if self._query_count >= config.max_query_count:
                self._budget_exhausted = True
                return 100_000

            branch_environment = environment.fork()
            observation: ToolLLMToolObservation | None = None
            if candidate.action_name is not None:
                observation = branch_environment.step(
                    candidate.action_name,
                    candidate.action_input,
                )
                if not isinstance(observation, ToolLLMToolObservation):
                    raise TypeError("ToolLLM environment step must return ToolLLMToolObservation")

            trajectory = parent.append_candidate(candidate, observation)
            siblings.append(trajectory)
            self._explored.append(trajectory)

            status = trajectory.terminal_status
            if status is ToolLLMObservationStatus.GIVE_ANSWER:
                self._terminal.append(trajectory)
                if len(self._terminal) >= config.answer_count:
                    return 10_000
                if not config.with_filter:
                    return config.final_answer_back_length
                continue
            if status is ToolLLMObservationStatus.GIVE_UP_AND_RESTART:
                self._give_up.append(trajectory)
                if not config.with_filter:
                    return config.prune_back_length
                continue

            if not config.with_filter:
                result = self._dfs(trajectory, branch_environment)
                if len(self._terminal) >= config.answer_count:
                    return 10_000
                if result > 1:
                    return result - 1
            else:
                branch_rows.append((trajectory, branch_environment))

        if not config.with_filter or not branch_rows:
            return 1

        assert self._ranker is not None
        trajectories = tuple(row[0] for row in branch_rows)
        ranked = self._ranker.rank(parent, trajectories)
        if not isinstance(ranked, ToolLLMDFSDTRankResult):
            raise TypeError("ToolLLM ranker must return ToolLLMDFSDTRankResult")
        if len(ranked.scores) != len(branch_rows):
            raise ValueError("ToolLLM ranker score count must match candidate count")
        self._query_count += ranked.query_count
        if self._query_count >= config.max_query_count:
            self._budget_exhausted = True
            return 100_000

        order = sorted(
            range(len(branch_rows)),
            key=lambda index: (-float(ranked.scores[index]), index),
        )
        for index in order:
            trajectory, branch_environment = branch_rows[index]
            result = self._dfs(trajectory, branch_environment)
            if len(self._terminal) >= config.answer_count:
                return 10_000
            if result > 1:
                return result - 1
        return 1


__all__ = [
    "ToolLLMBranchEnvironment",
    "ToolLLMDFSDTCandidate",
    "ToolLLMDFSDTConfig",
    "ToolLLMDFSDTGeneratorPort",
    "ToolLLMDFSDTNodeKind",
    "ToolLLMDFSDTRankResult",
    "ToolLLMDFSDTRankerPort",
    "ToolLLMDFSDTSearch",
    "ToolLLMDFSDTSearchResult",
    "ToolLLMDFSDTTraceNode",
    "ToolLLMDFSDTTrajectory",
    "ToolLLMObservationStatus",
    "ToolLLMToolObservation",
]
