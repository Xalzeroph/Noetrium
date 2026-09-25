from research.reproductions.camel_role_playing import CAMEL_ROLE_PLAYING_FIDELITY


def test_paper_era_camel_separates_constructor_defaults_from_ai_society_protocol() -> None:
    fidelity = CAMEL_ROLE_PLAYING_FIDELITY
    assert fidelity.participant_count == 2
    assert fidelity.required_roles == ("assistant", "user")
    assert fidelity.constructor_task_specification_default is True
    assert fidelity.constructor_task_planning_default is False
    assert fidelity.paper_task_specification is True
    assert fidelity.paper_task_planning is True
    assert fidelity.task_specifier_temperature == 1.4
    assert fidelity.default_chat_temperature == 0.2
    assert fidelity.role_conditioned_system_messages
    assert fidelity.task_conditioned_system_messages


def test_paper_era_camel_preserves_released_ai_society_dialogue_control() -> None:
    fidelity = CAMEL_ROLE_PLAYING_FIDELITY
    assert fidelity.turn_order == ("user_agent", "assistant_agent")
    assert fidelity.independent_agent_histories
    assert fidelity.reset_both_agents_before_init
    assert fidelity.hidden_assistant_bootstrap_call
    assert fidelity.token_overflow_terminates_agent
    assert fidelity.max_saved_messages == 40
    assert fidelity.user_no_instruction_threshold == 3
    assert fidelity.assistant_instruction_threshold == 1
    assert fidelity.repeated_word_threshold == 4
    assert fidelity.repeat_threshold_breaks_inner_loop_only is True
    assert fidelity.task_done_token == "<CAMEL_TASK_DONE>"
    assert fidelity.conversation_population == 25_000
    assert fidelity.paper_agent_evaluation_sample_size == 100
