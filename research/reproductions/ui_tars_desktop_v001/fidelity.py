from __future__ import annotations

from dataclasses import dataclass


UI_TARS_DESKTOP_V001_AUDITED_COMMIT = "f05568b147afb00ece8a16954f2e12c569699220"


@dataclass(frozen=True, slots=True)
class UiTarsDesktopV001Fidelity:
    """Earliest released UI-TARS Desktop computer-use semantics from 0.0.1."""

    source_repository: str = "https://github.com/bytedance/UI-TARS-desktop"
    audited_commit: str = UI_TARS_DESKTOP_V001_AUDITED_COMMIT
    release_version: str = "0.0.1"
    agent_loop_source: str = "src/main/agent/index.ts"
    parser_source: str = "packages/action-parser/src/index.ts"
    executor_source: str = "src/main/agent/execute.ts"
    coordinate_source: str = "src/main/utils/coords.ts"
    prompt_source: str = "src/main/agent/prompts.ts"
    constants_source: str = "packages/shared/src/constants/vlm.ts"
    coordinate_factor: int = 1000
    max_loop_count: int = 25
    max_retained_images: int = 5
    screenshot_retry_count: int = 5
    screenshot_failure_limit: int = 10
    image_placeholder: str = "<image>"
    action_grammar: tuple[str, ...] = (
        "click",
        "left_double",
        "right_single",
        "drag",
        "hotkey",
        "type",
        "scroll",
        "wait",
        "finished",
        "call_user",
    )
    terminal_actions: tuple[str, ...] = (
        "error_env",
        "call_user",
        "finished",
    )
    max_loop_action: str = "max_loop"
    multiple_actions_per_prediction: bool = True
    boxes_are_normalized_by_factor: bool = True
    two_coordinate_box_expands_to_point_box: bool = True
    execution_uses_current_snapshot_geometry: bool = True
    old_image_eviction_is_model_view_only: bool = True

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("UI-TARS Desktop audited commit must be a git SHA")
        if self.release_version != "0.0.1":
            raise ValueError("UI-TARS Desktop release identity drifted")
        if (
            self.coordinate_factor,
            self.max_loop_count,
            self.max_retained_images,
            self.screenshot_retry_count,
            self.screenshot_failure_limit,
        ) != (1000, 25, 5, 5, 10):
            raise ValueError("UI-TARS Desktop loop/vision defaults drifted")
        if self.image_placeholder != "<image>":
            raise ValueError("UI-TARS Desktop image placeholder drifted")
        if self.action_grammar != (
            "click",
            "left_double",
            "right_single",
            "drag",
            "hotkey",
            "type",
            "scroll",
            "wait",
            "finished",
            "call_user",
        ):
            raise ValueError("UI-TARS Desktop prompt action grammar drifted")
        if self.terminal_actions != ("error_env", "call_user", "finished"):
            raise ValueError("UI-TARS Desktop terminal action semantics drifted")
        if not all(
            (
                self.multiple_actions_per_prediction,
                self.boxes_are_normalized_by_factor,
                self.two_coordinate_box_expands_to_point_box,
                self.execution_uses_current_snapshot_geometry,
                self.old_image_eviction_is_model_view_only,
            )
        ):
            raise ValueError("UI-TARS Desktop grounding/model-view semantics drifted")


UI_TARS_DESKTOP_V001_FIDELITY = UiTarsDesktopV001Fidelity()


__all__ = [
    "UI_TARS_DESKTOP_V001_AUDITED_COMMIT",
    "UI_TARS_DESKTOP_V001_FIDELITY",
    "UiTarsDesktopV001Fidelity",
]
