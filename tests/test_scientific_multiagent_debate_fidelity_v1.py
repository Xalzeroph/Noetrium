from noetrium_platform.research.execution.workflow.api import MethodNodeKind
from research.reproductions.multiagent_debate import (
    MULTIAGENT_DEBATE_FIDELITY,
    MULTIAGENT_DEBATE_METHOD_PROGRAM,
)
from research.reproductions.multiagent_debate.definition import REPRODUCTION
from research.reproductions.research_os import (
    compile_reproduction_research_program,
    is_research_os_executable,
)


def test_multiagent_debate_preserves_three_agent_two_round_gsm_defaults() -> None:
    fidelity = MULTIAGENT_DEBATE_FIDELITY
    assert fidelity.default_agent_count == 3
    assert fidelity.default_round_count == 2
    assert fidelity.first_round_independent
    assert fidelity.independent_agent_contexts


def test_multiagent_debate_uses_previous_round_peer_snapshot() -> None:
    fidelity = MULTIAGENT_DEBATE_FIDELITY
    assert fidelity.subsequent_round_uses_other_agents_previous_round
    assert fidelity.round_information_semantics == "synchronous_previous_round_snapshot"
    assert fidelity.self_previous_response_remains_in_local_context
    assert fidelity.peer_responses_are_injected_as_user_information



def test_multiagent_debate_method_program_preserves_explicit_two_round_three_agent_graph() -> None:
    program = MULTIAGENT_DEBATE_METHOD_PROGRAM
    agent_nodes = tuple(
        node for node in program.graph.nodes
        if node.kind is MethodNodeKind.AGENT
    )

    assert len(agent_nodes) == 6
    assert tuple(node.node_id for node in agent_nodes) == (
        "round1_agent_0",
        "round1_agent_1",
        "round1_agent_2",
        "round2_agent_0",
        "round2_agent_1",
        "round2_agent_2",
    )
    assert tuple(node.agent_id for node in agent_nodes[:3]) == (
        "multiagent-debate.agent-0",
        "multiagent-debate.agent-1",
        "multiagent-debate.agent-2",
    )
    assert tuple(node.agent_id for node in agent_nodes[3:]) == (
        "multiagent-debate.agent-0",
        "multiagent-debate.agent-1",
        "multiagent-debate.agent-2",
    )
    assert program.configuration["round_information_semantics"] == (
        "synchronous_previous_round_snapshot"
    )
    assert program.configuration["peer_responses_are_injected_as_user_information"] is True
    assert program.configuration["independent_agent_contexts"] is True


def test_multiagent_debate_enters_current_top_level_research_os() -> None:
    assert is_research_os_executable(REPRODUCTION)
    research_program = compile_reproduction_research_program(REPRODUCTION)

    assert research_program.program_id == "multiagent_debate"
    assert tuple(node.node_id for node in research_program.nodes) == ("reproduction",)
    method = next(
        definition
        for definition in research_program.definitions
        if definition.definition_id == "method"
    )
    assert method.implementation is not None
    assert method.implementation.program_digest == (
        MULTIAGENT_DEBATE_METHOD_PROGRAM.program_digest
    )
