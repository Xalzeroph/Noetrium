from research.reproductions.camel_role_playing import CAMEL_ROLE_PLAYING_FIDELITY


def test_paper_era_camel_is_two_role_inception_prompting_not_modern_framework() -> None:
    fidelity = CAMEL_ROLE_PLAYING_FIDELITY
    assert fidelity.participant_count == 2
    assert fidelity.required_roles == ("assistant", "user")
    assert fidelity.task_specification_default
    assert fidelity.task_planning_default is False
    assert fidelity.role_conditioned_system_messages
    assert fidelity.task_conditioned_system_messages


def test_paper_era_camel_preserves_alternating_independent_dialogue_histories() -> None:
    fidelity = CAMEL_ROLE_PLAYING_FIDELITY
    assert fidelity.turn_order == ("user_agent", "assistant_agent")
    assert fidelity.independent_agent_histories
    assert fidelity.reset_both_agents_before_init
    assert fidelity.initial_instruction_constraint == "Instruction_and_Input_only"
    assert fidelity.token_overflow_terminates_agent
    assert fidelity.optional_message_window_projection
