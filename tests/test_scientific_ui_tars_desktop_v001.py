from __future__ import annotations

from research.reproductions.ui_tars_desktop_v001 import (
    UI_TARS_DESKTOP_V001_AUDITED_COMMIT,
    UI_TARS_DESKTOP_V001_FIDELITY,
    UiTarsDesktopV001Conversation,
    UiTarsDesktopV001LoopState,
    UiTarsDesktopV001Status,
    parse_ui_tars_desktop_v001_prediction,
    project_ui_tars_desktop_v001_vlm_view,
    ui_tars_desktop_v001_box_to_screen_point,
    ui_tars_desktop_v001_should_dispatch_to_device,
)


def test_ui_tars_desktop_v001_release_and_desktop_defaults_are_pinned() -> None:
    fidelity = UI_TARS_DESKTOP_V001_FIDELITY
    assert UI_TARS_DESKTOP_V001_AUDITED_COMMIT == (
        "f05568b147afb00ece8a16954f2e12c569699220"
    )
    assert fidelity.release_version == "0.0.1"
    assert fidelity.coordinate_factor == 1000
    assert fidelity.max_loop_count == 25
    assert fidelity.max_retained_images == 5
    assert fidelity.screenshot_retry_count == 5
    assert fidelity.screenshot_failure_limit == 10
    assert fidelity.image_placeholder == "<image>"
    assert fidelity.multiple_actions_per_prediction is True
    assert fidelity.execution_uses_current_snapshot_geometry is True
    assert fidelity.old_image_eviction_is_model_view_only is True


def test_ui_tars_desktop_v001_parser_preserves_multi_action_and_grounding_semantics() -> None:
    actions = parse_ui_tars_desktop_v001_prediction(
        "Thought: inspect the current desktop\n"
        "Action: click(start_box='(250,500)')\n\n"
        "type(content='hello, world')"
    )

    assert [action.action_type for action in actions] == ["click", "type"]
    assert all(action.thought == "inspect the current desktop" for action in actions)
    assert actions[0].reflection == ""
    assert actions[0].input("start_box") == "[0.25,0.5,0.25,0.5]"
    assert actions[1].input("content") == "hello, world"


def test_ui_tars_desktop_v001_parser_expands_points_and_uses_only_last_action_section() -> None:
    actions = parse_ui_tars_desktop_v001_prediction(
        "Action: click(start_box='(100,200)')\n"
        "Action: drag(start_box='(100,200)', end_box='(700,800)')"
    )

    assert len(actions) == 1
    assert actions[0].action_type == "drag"
    assert actions[0].input("start_box") == "[0.1,0.2,0.1,0.2]"
    assert actions[0].input("end_box") == "[0.7,0.8,0.7,0.8]"


def test_ui_tars_desktop_v001_reflection_and_action_summary_share_prediction_metadata() -> None:
    actions = parse_ui_tars_desktop_v001_prediction(
        "Reflection: The prior click missed the target.\n"
        "Action_Summary: Move to the corrected target.\n"
        "Action: click(start_box='(500,500)')"
    )

    assert len(actions) == 1
    assert actions[0].reflection == "The prior click missed the target."
    assert actions[0].thought == "Move to the corrected target."


def test_ui_tars_desktop_v001_vlm_projection_bounds_images_without_rewriting_host_truth() -> None:
    conversations = [UiTarsDesktopV001Conversation("human", "complete the task")]
    for index in range(7):
        conversations.extend(
            (
                UiTarsDesktopV001Conversation("human", "<image>"),
                UiTarsDesktopV001Conversation("gpt", f"step-{index}"),
            )
        )
    host_truth = tuple(conversations)
    images = tuple(f"image-{index}" for index in range(7))

    view = project_ui_tars_desktop_v001_vlm_view(host_truth, images)

    assert tuple(conversations) == host_truth
    assert images == tuple(f"image-{index}" for index in range(7))
    assert view.images == ("image-2", "image-3", "image-4", "image-5", "image-6")
    assert sum(message.value == "<image>" for message in view.conversations) == 5
    assert "step-0" in [message.value for message in view.conversations]
    assert "step-1" in [message.value for message in view.conversations]
    assert len(view.conversations) == len(host_truth) - 2


def test_ui_tars_desktop_v001_screen_projection_uses_box_center_current_geometry_and_js_rounding() -> None:
    point = ui_tars_desktop_v001_box_to_screen_point(
        "[0.25,0.5,0.25,0.5]",
        width=1920,
        height=1080,
    )
    assert (point.x, point.y) == (480.0, 540.0)

    half_step = ui_tars_desktop_v001_box_to_screen_point(
        "[0,0,0.001,0.001]",
        width=1,
        height=1,
    )
    assert (half_step.x, half_step.y) == (0.001, 0.001)


def test_ui_tars_desktop_v001_loop_allows_24_counted_iterations_then_stops_before_25th_snapshot() -> None:
    state = UiTarsDesktopV001LoopState().start()
    for expected_count in range(1, 25):
        state = state.begin_iteration()
        assert state.loop_count == expected_count
        assert state.status is UiTarsDesktopV001Status.RUNNING

    state = state.begin_iteration()
    assert state.loop_count == 25
    assert state.status is UiTarsDesktopV001Status.MAX_LOOP


def test_ui_tars_desktop_v001_invalid_snapshots_do_not_consume_loop_budget_and_stop_at_ten_failures() -> None:
    state = UiTarsDesktopV001LoopState().start()
    for expected_errors in range(1, 11):
        state = state.begin_iteration().record_invalid_snapshot()
        assert state.loop_count == 0
        assert state.snapshot_error_count == expected_errors
        assert state.status is UiTarsDesktopV001Status.RUNNING

    state = state.begin_iteration()
    assert state.loop_count == 1
    assert state.snapshot_error_count == 10
    assert state.status is UiTarsDesktopV001Status.MAX_LOOP


def test_ui_tars_desktop_v001_action_batch_status_and_dispatch_match_source_ordering() -> None:
    state = UiTarsDesktopV001LoopState().start().begin_iteration()

    state = state.apply_action("finished")
    assert state.status is UiTarsDesktopV001Status.END
    assert ui_tars_desktop_v001_should_dispatch_to_device("finished") is True

    state = state.apply_action("click")
    assert state.status is UiTarsDesktopV001Status.RUNNING
    assert ui_tars_desktop_v001_should_dispatch_to_device("click") is True

    state = state.apply_action("max_loop")
    assert state.status is UiTarsDesktopV001Status.MAX_LOOP
    assert ui_tars_desktop_v001_should_dispatch_to_device("wait") is False
    assert ui_tars_desktop_v001_should_dispatch_to_device("click", aborted=True) is False


def test_ui_tars_desktop_v001_scaffold_does_not_claim_platform_journal_or_device_authority() -> None:
    state = UiTarsDesktopV001LoopState().start()
    action = parse_ui_tars_desktop_v001_prediction("Action: finished()")

    assert len(action) == 1
    assert not hasattr(state, "journal")
    assert not hasattr(state, "messages")
    assert not hasattr(action[0], "device")
    assert not hasattr(action[0], "capability")
