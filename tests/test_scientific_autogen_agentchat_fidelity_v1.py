from research.reproductions.autogen_agentchat import AUTOGEN_AGENTCHAT_FIDELITY


def test_early_autogen_preserves_conversable_mixed_capability_agents() -> None:
    fidelity = AUTOGEN_AGENTCHAT_FIDELITY
    assert fidelity.agents_are_customizable_conversable_participants
    assert fidelity.supports_llm_human_tool_combinations
    assert fidelity.user_proxy_default_human_input_mode == "ALWAYS"
    assert fidelity.user_proxy_llm_auto_reply_default is False
    assert fidelity.user_proxy_code_execution_enabled_by_default
    assert fidelity.user_proxy_default_docker_code_execution


def test_early_autogen_groupchat_preserves_selector_and_broadcast_semantics() -> None:
    fidelity = AUTOGEN_AGENTCHAT_FIDELITY
    assert fidelity.groupchat_default_max_round == 10
    assert fidelity.groupchat_broadcast_excludes_speaker
    assert fidelity.next_speaker_selected_from_conversation
    assert fidelity.invalid_or_failed_speaker_selection_falls_back_round_robin
    assert fidelity.admin_can_take_over_on_interrupt
    assert fidelity.human_input_modes == ("ALWAYS", "TERMINATE", "NEVER")
