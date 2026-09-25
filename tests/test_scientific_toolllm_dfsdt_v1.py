from __future__ import annotations

from dataclasses import dataclass

from research.reproductions.toolllm_toolbench.search import (
    ToolLLMDFSDTCandidate,
    ToolLLMDFSDTConfig,
    ToolLLMDFSDTNodeKind,
    ToolLLMDFSDTRankResult,
    ToolLLMDFSDTSearch,
    ToolLLMObservationStatus,
    ToolLLMToolObservation,
)


@dataclass
class _Environment:
    responses: dict[str, ToolLLMToolObservation]
    actions: list[str]
    fork_count: list[int]

    def fork(self) -> _Environment:
        self.fork_count[0] += 1
        return _Environment(self.responses, self.actions, self.fork_count)

    def step(self, action_name: str, action_input: str) -> ToolLLMToolObservation:
        self.actions.append(action_name)
        return self.responses[action_name]


def test_toolllm_status_codes_match_paper_rapidapi_contract() -> None:
    assert [status.value for status in ToolLLMObservationStatus] == list(range(13))
    assert ToolLLMObservationStatus.GIVE_ANSWER.value == 3
    assert ToolLLMObservationStatus.GIVE_UP_AND_RESTART.value == 4


def test_dfsdt_records_thought_action_input_and_terminal_observation() -> None:
    class Generator:
        def generate(self, trajectory, previous_siblings):
            return ToolLLMDFSDTCandidate("inspect result", "Finish", '{"return_type":"give_answer"}')

    environment = _Environment(
        {"Finish": ToolLLMToolObservation("success", ToolLLMObservationStatus.GIVE_ANSWER)},
        [],
        [0],
    )
    result = ToolLLMDFSDTSearch(
        Generator(),
        ToolLLMDFSDTConfig(3, 1, 10),
    ).run(environment)

    assert result.solved is True
    assert result.query_count == 1
    assert environment.fork_count == [1]
    trajectory = result.terminal[0]
    assert tuple(node.kind for node in trajectory.nodes) == (
        ToolLLMDFSDTNodeKind.THOUGHT,
        ToolLLMDFSDTNodeKind.ACTION,
        ToolLLMDFSDTNodeKind.ACTION_INPUT,
    )
    assert trajectory.nodes[-1].observation == "success"
    assert trajectory.nodes[-1].observation_status is ToolLLMObservationStatus.GIVE_ANSWER


def test_dfsdt_query_budget_stops_before_executing_limit_reaching_response() -> None:
    class Generator:
        def generate(self, trajectory, previous_siblings):
            return ToolLLMDFSDTCandidate(action_name="tool", action_input="{}")

    environment = _Environment(
        {"tool": ToolLLMToolObservation("unused", ToolLLMObservationStatus.OK)},
        [],
        [0],
    )
    result = ToolLLMDFSDTSearch(
        Generator(),
        ToolLLMDFSDTConfig(2, 1, 1),
    ).run(environment)

    assert result.budget_exhausted is True
    assert result.query_count == 1
    assert result.explored == ()
    assert environment.actions == []
    assert environment.fork_count == [0]


def test_dfsdt_give_up_status_prunes_branch() -> None:
    class Generator:
        def generate(self, trajectory, previous_siblings):
            return ToolLLMDFSDTCandidate(action_name="Finish", action_input="give-up")

    environment = _Environment(
        {
            "Finish": ToolLLMToolObservation(
                "restart",
                ToolLLMObservationStatus.GIVE_UP_AND_RESTART,
            )
        },
        [],
        [0],
    )
    result = ToolLLMDFSDTSearch(
        Generator(),
        ToolLLMDFSDTConfig(3, 1, 10, prune_back_length=2),
    ).run(environment)

    assert result.solved is False
    assert len(result.give_up) == 1
    assert result.give_up[0].terminal_status is ToolLLMObservationStatus.GIVE_UP_AND_RESTART


def test_filtered_dfsdt_generates_diverse_siblings_then_expands_ranked_branch() -> None:
    class Generator:
        def __init__(self) -> None:
            self.sibling_counts: list[int] = []

        def generate(self, trajectory, previous_siblings):
            self.sibling_counts.append(len(previous_siblings))
            if not trajectory.nodes:
                action = "root-a" if not previous_siblings else "root-b"
                return ToolLLMDFSDTCandidate(action_name=action, action_input="{}")
            parent_action = trajectory.nodes[-2].content
            if parent_action == "root-b":
                return ToolLLMDFSDTCandidate(action_name="finish-b", action_input="{}")
            return ToolLLMDFSDTCandidate(action_name="giveup-a", action_input="{}")

    class Ranker:
        def rank(self, parent, candidates):
            assert len(candidates) == 2
            return ToolLLMDFSDTRankResult((0.1, 0.9), query_count=1)

    generator = Generator()
    environment = _Environment(
        {
            "root-a": ToolLLMToolObservation("a", ToolLLMObservationStatus.OK),
            "root-b": ToolLLMToolObservation("b", ToolLLMObservationStatus.OK),
            "finish-b": ToolLLMToolObservation("answer", ToolLLMObservationStatus.GIVE_ANSWER),
            "giveup-a": ToolLLMToolObservation("restart", ToolLLMObservationStatus.GIVE_UP_AND_RESTART),
        },
        [],
        [0],
    )
    result = ToolLLMDFSDTSearch(
        generator,
        ToolLLMDFSDTConfig(
            max_reasoning_steps=2,
            tree_beam_size=2,
            max_query_count=20,
            with_filter=True,
        ),
        ranker=Ranker(),
    ).run(environment)

    assert result.solved is True
    assert generator.sibling_counts[:2] == [0, 1]
    assert environment.actions[:3] == ["root-a", "root-b", "finish-b"]
    assert result.terminal[0].nodes[-2].content == "finish-b"
    assert environment.fork_count[0] >= 3
