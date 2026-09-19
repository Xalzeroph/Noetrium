from research.reproductions.agent_s3 import (
    AGENT_S3_FIDELITY,
    AgentS3GeneratorTurn,
    AgentS3ReflectionTurn,
    project_agent_s3_context,
)


def _generator_turn(index: int) -> AgentS3GeneratorTurn:
    return AgentS3GeneratorTurn(
        user_text=f"user-{index}",
        assistant_text=f"assistant-{index}",
        screenshot_ref=f"image-{index}",
    )


def _reflection_turn(index: int) -> AgentS3ReflectionTurn:
    return AgentS3ReflectionTurn(
        text=f"reflection-{index}",
        screenshot_ref=f"reflection-image-{index}",
    )


def test_agent_s3_fidelity_keeps_s3_distinct_from_hierarchy_and_bbon() -> None:
    assert AGENT_S3_FIDELITY.release == "v0.3.2"
    assert AGENT_S3_FIDELITY.hierarchy_enabled is False
    assert AGENT_S3_FIDELITY.default_max_trajectory_length == 8
    assert AGENT_S3_FIDELITY.default_reflection_enabled is True
    assert AGENT_S3_FIDELITY.behavior_best_of_n_is_separate is True
    assert AGENT_S3_FIDELITY.code_agent_budget == 20


def test_long_context_view_keeps_all_text_but_only_latest_images() -> None:
    generator = tuple(_generator_turn(index) for index in range(4))
    reflection = tuple(_reflection_turn(index) for index in range(4))

    view = project_agent_s3_context(
        generator_turns=generator,
        reflection_turns=reflection,
        engine_type="openai",
        max_trajectory_length=2,
    )

    assert len(view.generator_turns) == 4
    assert len(view.reflection_turns) == 4
    assert [turn.user_text for turn in view.generator_turns] == [
        "user-0",
        "user-1",
        "user-2",
        "user-3",
    ]
    assert [turn.screenshot_ref for turn in view.generator_turns] == [
        None,
        None,
        "image-2",
        "image-3",
    ]
    assert [turn.screenshot_ref for turn in view.reflection_turns] == [
        None,
        None,
        "reflection-image-2",
        "reflection-image-3",
    ]


def test_non_long_context_view_drops_oldest_complete_turns() -> None:
    generator = tuple(_generator_turn(index) for index in range(4))
    reflection = tuple(_reflection_turn(index) for index in range(4))

    view = project_agent_s3_context(
        generator_turns=generator,
        reflection_turns=reflection,
        engine_type="vllm",
        max_trajectory_length=2,
    )

    assert [turn.user_text for turn in view.generator_turns] == ["user-2", "user-3"]
    assert [turn.text for turn in view.reflection_turns] == ["reflection-2", "reflection-3"]
    assert [turn.screenshot_ref for turn in view.generator_turns] == ["image-2", "image-3"]


def test_agent_s3_projection_does_not_mutate_host_history() -> None:
    generator = tuple(_generator_turn(index) for index in range(3))
    reflection = tuple(_reflection_turn(index) for index in range(3))

    view = project_agent_s3_context(
        generator_turns=generator,
        reflection_turns=reflection,
        engine_type="anthropic",
        max_trajectory_length=1,
    )

    assert generator[0].screenshot_ref == "image-0"
    assert reflection[0].screenshot_ref == "reflection-image-0"
    assert view.generator_turns[0].screenshot_ref is None
    assert view.reflection_turns[0].screenshot_ref is None
