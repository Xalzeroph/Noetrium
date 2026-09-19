from __future__ import annotations

import hashlib

from research.reproductions.chatdev_v1 import (
    CHATDEV_V1_AUDITED_COMMIT,
    CHATDEV_V1_AUDITED_TAG,
    CHATDEV_V1_COMPOSED_PHASES,
    CHATDEV_V1_REFERENCE_FIDELITY,
    CHATDEV_V1_SIMPLE_PHASES,
    CHATDEV_V1_TOP_LEVEL_CHAIN,
    ChatDevV1ComposedPhaseSpec,
    ChatDevV1PhaseReceipt,
    ChatDevV1SimplePhaseSpec,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_chatdev_v1_official_release_cut_and_default_chain_are_pinned() -> None:
    fidelity = CHATDEV_V1_REFERENCE_FIDELITY
    assert CHATDEV_V1_AUDITED_TAG == "v1.0.0"
    assert CHATDEV_V1_AUDITED_COMMIT == "acb93cf3d15cec5b9ee6eec0850ddd3932164329"
    assert fidelity.top_level_phase_order == (
        "DemandAnalysis",
        "LanguageChoose",
        "Coding",
        "CodeCompleteAll",
        "CodeReview",
        "Test",
        "EnvironmentDoc",
        "Manual",
    )
    assert fidelity.default_chat_turn_limit == 10
    assert fidelity.reflection_phases == (
        "DemandAnalysis",
        "LanguageChoose",
        "EnvironmentDoc",
    )
    assert fidelity.reflection_roles == ("Chief Executive Officer", "Counselor")


def test_chatdev_v1_does_not_backport_later_hai_git_or_self_improvement_semantics() -> None:
    fidelity = CHATDEV_V1_REFERENCE_FIDELITY
    assert fidelity.git_management is False
    assert fidelity.self_improve is False
    assert fidelity.brainstorming is False
    assert fidelity.gui_design is True
    assert fidelity.nested_composed_phases_supported is False
    assert "Human" not in fidelity.recruitments
    assert "Prompt Engineer" not in fidelity.recruitments


def test_chatdev_v1_exact_role_pairs_and_reflection_flags_are_method_owned() -> None:
    expected = {
        "DemandAnalysis": ("Chief Product Officer", "Chief Executive Officer", 10, True),
        "LanguageChoose": ("Chief Technology Officer", "Chief Executive Officer", 10, True),
        "Coding": ("Programmer", "Chief Technology Officer", 1, False),
        "CodeComplete": ("Programmer", "Chief Technology Officer", 1, False),
        "CodeReviewComment": ("Code Reviewer", "Programmer", 1, False),
        "CodeReviewModification": ("Programmer", "Code Reviewer", 1, False),
        "TestErrorSummary": ("Programmer", "Software Test Engineer", 1, False),
        "TestModification": ("Programmer", "Software Test Engineer", 1, False),
        "EnvironmentDoc": ("Programmer", "Chief Technology Officer", 1, True),
        "Manual": ("Chief Product Officer", "Chief Executive Officer", 1, False),
    }
    for phase_name, values in expected.items():
        phase = CHATDEV_V1_SIMPLE_PHASES[phase_name]
        assert (
            phase.assistant_role,
            phase.user_role,
            phase.max_turns,
            phase.reflect,
        ) == values


def test_chatdev_v1_composed_phases_preserve_bounded_cycles_and_source_early_stops() -> None:
    code_complete = CHATDEV_V1_COMPOSED_PHASES["CodeCompleteAll"]
    review = CHATDEV_V1_COMPOSED_PHASES["CodeReview"]
    test = CHATDEV_V1_COMPOSED_PHASES["Test"]

    assert code_complete.cycle_limit == 10
    assert [phase.name for phase in code_complete.composition] == ["CodeComplete"]
    assert code_complete.stop_condition == "unimplemented_file_is_empty"
    assert review.cycle_limit == 3
    assert [phase.name for phase in review.composition] == [
        "CodeReviewComment",
        "CodeReviewModification",
    ]
    assert review.stop_condition == "modification_conclusion_contains_info_finished"
    assert test.cycle_limit == 3
    assert [phase.name for phase in test.composition] == [
        "TestErrorSummary",
        "TestModification",
    ]
    assert test.stop_condition == "exist_bugs_flag_is_false"


def test_chatdev_v1_top_level_chain_keeps_simple_and_composed_structure_without_new_vm() -> None:
    assert [phase.name for phase in CHATDEV_V1_TOP_LEVEL_CHAIN] == list(
        CHATDEV_V1_REFERENCE_FIDELITY.top_level_phase_order
    )
    assert isinstance(CHATDEV_V1_TOP_LEVEL_CHAIN[0], ChatDevV1SimplePhaseSpec)
    assert isinstance(CHATDEV_V1_TOP_LEVEL_CHAIN[3], ChatDevV1ComposedPhaseSpec)
    assert isinstance(CHATDEV_V1_TOP_LEVEL_CHAIN[4], ChatDevV1ComposedPhaseSpec)
    assert isinstance(CHATDEV_V1_TOP_LEVEL_CHAIN[5], ChatDevV1ComposedPhaseSpec)


def test_chatdev_v1_phase_receipts_bind_state_transition_identity_without_owning_platform_journal() -> None:
    receipt = ChatDevV1PhaseReceipt(
        phase_name="Coding",
        input_state_digest=_digest("before-coding"),
        output_state_digest=_digest("after-coding"),
    )
    assert receipt.cycle_index == 0
    assert len(receipt.digest()) == 64
    assert not hasattr(receipt, "messages")
    assert not hasattr(receipt, "journal")
