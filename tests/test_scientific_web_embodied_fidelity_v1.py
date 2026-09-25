from research.reproductions.voyager_minecraft import VOYAGER_MINECRAFT_FIDELITY
from research.reproductions.webvoyager import WEBVOYAGER_FIDELITY


def test_webvoyager_preserves_labeled_multimodal_observation_and_action_grammar() -> None:
    fidelity = WEBVOYAGER_FIDELITY
    assert fidelity.observation_mode == "labeled_screenshot_plus_text"
    assert fidelity.text_only_alternative == "labeled_accessibility_tree"
    assert fidelity.one_action_per_iteration
    assert fidelity.action_grammar == (
        "Click",
        "Type",
        "Scroll",
        "Wait",
        "GoBack",
        "Google",
        "ANSWER",
    )
    assert fidelity.wait_seconds == 5
    assert fidelity.numerical_element_grounding


def test_voyager_preserves_method_owned_curriculum_skill_and_program_improvement() -> None:
    fidelity = VOYAGER_MINECRAFT_FIDELITY
    assert fidelity.automatic_curriculum
    assert fidelity.executable_skill_library
    assert fidelity.skill_retrieval
    assert fidelity.iterative_program_improvement
    assert fidelity.improvement_feedback == (
        "environment_feedback",
        "execution_errors",
        "self_verification",
    )
    assert fidelity.model_parameter_finetuning is False
    assert fidelity.learning_resume_from_checkpoint
    assert fidelity.inference_uses_learned_skill_library
    assert fidelity.inference_task_decomposition
    assert fidelity.audited_commit == (
        "edeee8383a22b96b54bff51c6cf809306a7b34a3"
    )
    assert fidelity.skill_retrieval_top_k == 5
    assert fidelity.max_learning_iterations == 160
    assert fidelity.action_task_max_retries == 4
