from research.reproductions.multiagent_debate import MULTIAGENT_DEBATE_FIDELITY


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
