from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
import json
import math
import re

from .fidelity import UI_TARS_DESKTOP_V001_FIDELITY


_ACTION_CALL = re.compile(r"^(\w+)\((.*)\)$", re.DOTALL)
_ARG_PAIR = re.compile(r"(?:[^,']|'[^']*')+")


class UiTarsDesktopV001Status(StrEnum):
    INIT = "init"
    RUNNING = "running"
    END = "end"
    MAX_LOOP = "max_loop"


@dataclass(frozen=True, slots=True)
class UiTarsDesktopV001Action:
    reflection: str
    thought: str
    action_type: str
    action_inputs: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.reflection, str) or not isinstance(self.thought, str):
            raise TypeError("UI-TARS reflection/thought must be text")
        if not isinstance(self.action_type, str) or not self.action_type.strip():
            raise ValueError("UI-TARS action_type is required")
        if self.action_type != self.action_type.strip():
            raise ValueError("UI-TARS action_type must be canonical")
        names: set[str] = set()
        for item in self.action_inputs:
            if (
                not isinstance(item, tuple)
                or len(item) != 2
                or not all(isinstance(value, str) for value in item)
            ):
                raise TypeError("UI-TARS action inputs must be (name, value) text pairs")
            name, _ = item
            if not name or name != name.strip() or name in names:
                raise ValueError("UI-TARS action input names must be unique canonical text")
            names.add(name)

    def input(self, name: str, default: str | None = None) -> str | None:
        for key, value in self.action_inputs:
            if key == name:
                return value
        return default


@dataclass(frozen=True, slots=True)
class UiTarsDesktopV001Conversation:
    from_role: str
    value: str

    def __post_init__(self) -> None:
        if self.from_role not in {"human", "gpt"}:
            raise ValueError("UI-TARS conversation role must be human or gpt")
        if not isinstance(self.value, str):
            raise TypeError("UI-TARS conversation value must be text")


@dataclass(frozen=True, slots=True)
class UiTarsDesktopV001VlmView:
    conversations: tuple[UiTarsDesktopV001Conversation, ...]
    images: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UiTarsDesktopV001ScreenPoint:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class UiTarsDesktopV001LoopState:
    loop_count: int = 0
    snapshot_error_count: int = 0
    status: UiTarsDesktopV001Status = UiTarsDesktopV001Status.INIT

    def __post_init__(self) -> None:
        if type(self.loop_count) is not int or self.loop_count < 0:
            raise ValueError("UI-TARS loop_count must be a non-negative int")
        if type(self.snapshot_error_count) is not int or self.snapshot_error_count < 0:
            raise ValueError("UI-TARS snapshot_error_count must be a non-negative int")
        if not isinstance(self.status, UiTarsDesktopV001Status):
            raise TypeError("UI-TARS loop status must be UiTarsDesktopV001Status")

    def start(self) -> UiTarsDesktopV001LoopState:
        return replace(self, status=UiTarsDesktopV001Status.RUNNING)

    def begin_iteration(self) -> UiTarsDesktopV001LoopState:
        if self.status is not UiTarsDesktopV001Status.RUNNING:
            return self
        loop_count = self.loop_count + 1
        if (
            loop_count >= UI_TARS_DESKTOP_V001_FIDELITY.max_loop_count
            or self.snapshot_error_count
            >= UI_TARS_DESKTOP_V001_FIDELITY.screenshot_failure_limit
        ):
            return replace(
                self,
                loop_count=loop_count,
                status=UiTarsDesktopV001Status.MAX_LOOP,
            )
        return replace(self, loop_count=loop_count)

    def record_invalid_snapshot(self) -> UiTarsDesktopV001LoopState:
        if self.status is not UiTarsDesktopV001Status.RUNNING or self.loop_count <= 0:
            raise ValueError("UI-TARS invalid snapshot requires an active counted iteration")
        return replace(
            self,
            loop_count=self.loop_count - 1,
            snapshot_error_count=self.snapshot_error_count + 1,
        )

    def apply_action(self, action_type: str) -> UiTarsDesktopV001LoopState:
        if action_type in UI_TARS_DESKTOP_V001_FIDELITY.terminal_actions:
            status = UiTarsDesktopV001Status.END
        elif action_type == UI_TARS_DESKTOP_V001_FIDELITY.max_loop_action:
            status = UiTarsDesktopV001Status.MAX_LOOP
        else:
            status = UiTarsDesktopV001Status.RUNNING
        return replace(self, status=status)


def _strip_boundary_quotes(value: str) -> str:
    if value[:1] in {"'", '"'}:
        value = value[1:]
    if value[-1:] in {"'", '"'}:
        value = value[:-1]
    return value


def _parse_action_call(raw: str) -> tuple[str, tuple[tuple[str, str], ...]] | None:
    match = _ACTION_CALL.fullmatch(raw.strip())
    if match is None:
        return None
    function_name, args_text = match.groups()
    pairs: list[tuple[str, str]] = []
    if args_text.strip():
        for pair_match in _ARG_PAIR.finditer(args_text):
            pair = pair_match.group(0)
            key, separator, value = pair.partition("=")
            if not key:
                continue
            value = value if separator else ""
            key = key.strip()
            value = _strip_boundary_quotes(value.strip())
            pairs.append((key, value))
    return function_name, tuple(pairs)


def _normalize_box(value: str, factor: int) -> str:
    numbers = [
        float(item) / factor
        for item in value.replace("(", "").replace(")", "").split(",")
    ]
    if len(numbers) == 2:
        numbers.extend(numbers)
    return json.dumps(numbers, separators=(",", ":"), allow_nan=False)


def parse_ui_tars_desktop_v001_prediction(
    prediction: str,
    *,
    factor: int = UI_TARS_DESKTOP_V001_FIDELITY.coordinate_factor,
) -> tuple[UiTarsDesktopV001Action, ...]:
    """Reproduce the public 0.0.1 BC action-parser behavior used by Desktop."""
    if not isinstance(prediction, str):
        raise TypeError("UI-TARS prediction must be text")
    if type(factor) is not int or factor <= 0:
        raise ValueError("UI-TARS coordinate factor must be a positive int")

    text = prediction.strip()
    reflection = ""
    thought = ""

    if text.startswith("Thought:"):
        match = re.search(r"Thought: ([\s\S]+?)(?=\s*Action:|$)", text)
        if match:
            thought = match.group(1).strip()
    elif text.startswith("Reflection:"):
        match = re.search(
            r"Reflection: ([\s\S]+?)Action_Summary: ([\s\S]+?)(?=\s*Action:|$)",
            text,
        )
        if match:
            reflection = match.group(1).strip()
            thought = match.group(2).strip()
    elif text.startswith("Action_Summary:"):
        match = re.search(r"Action_Summary: (.+?)(?=\s*Action:|$)", text)
        if match:
            thought = match.group(1).strip()

    action_text = text.rsplit("Action:", 1)[-1] if "Action:" in text else text
    actions: list[UiTarsDesktopV001Action] = []
    for raw in action_text.split("\n\n"):
        parsed = _parse_action_call(raw.replace("\n", r"\n").strip())
        if parsed is None:
            continue
        action_type, raw_inputs = parsed
        inputs: list[tuple[str, str]] = []
        for name, value in raw_inputs:
            if not value:
                continue
            normalized = (
                _normalize_box(value, factor)
                if "start_box" in name or "end_box" in name
                else value.strip()
            )
            inputs.append((name.strip(), normalized))
        actions.append(
            UiTarsDesktopV001Action(
                reflection=reflection,
                thought=thought,
                action_type=action_type,
                action_inputs=tuple(inputs),
            )
        )
    return tuple(actions)


def project_ui_tars_desktop_v001_vlm_view(
    conversations: Sequence[UiTarsDesktopV001Conversation],
    images: Sequence[str],
    *,
    max_images: int = UI_TARS_DESKTOP_V001_FIDELITY.max_retained_images,
) -> UiTarsDesktopV001VlmView:
    """Project host truth into the bounded 0.0.1 VLM request without mutating history."""
    if type(max_images) is not int or max_images <= 0:
        raise ValueError("UI-TARS max_images must be a positive int")
    projected_conversations = tuple(conversations)
    projected_images = tuple(images)
    if len(projected_images) <= max_images:
        return UiTarsDesktopV001VlmView(projected_conversations, projected_images)

    excess = len(projected_images) - max_images
    projected_images = projected_images[excess:]
    to_remove = excess
    retained: list[UiTarsDesktopV001Conversation] = []
    for conversation in projected_conversations:
        if (
            to_remove > 0
            and conversation.value == UI_TARS_DESKTOP_V001_FIDELITY.image_placeholder
        ):
            to_remove -= 1
            continue
        retained.append(conversation)
    return UiTarsDesktopV001VlmView(tuple(retained), projected_images)


def _js_round(value: float) -> int:
    if not math.isfinite(value):
        raise ValueError("UI-TARS screen coordinate must be finite")
    return math.floor(value + 0.5)


def ui_tars_desktop_v001_box_to_screen_point(
    box: str,
    *,
    width: int,
    height: int,
    precision_factor: int = UI_TARS_DESKTOP_V001_FIDELITY.coordinate_factor,
) -> UiTarsDesktopV001ScreenPoint:
    """Match parseBoxToScreenCoords: box center times current screenshot geometry."""
    if type(width) is not int or width <= 0 or type(height) is not int or height <= 0:
        raise ValueError("UI-TARS screenshot geometry must use positive integer dimensions")
    if type(precision_factor) is not int or precision_factor <= 0:
        raise ValueError("UI-TARS precision_factor must be a positive int")

    values = [
        float(item.strip())
        for item in box.replace("[", "").replace("]", "").split(",")
    ]
    if len(values) == 2:
        x1, y1 = values
        x2, y2 = x1, y1
    elif len(values) == 4:
        x1, y1, x2, y2 = values
    else:
        raise ValueError("UI-TARS box must contain two or four coordinates")
    if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
        raise ValueError("UI-TARS box coordinates must be finite")

    x_scaled = ((x1 + x2) / 2) * width * precision_factor
    y_scaled = ((y1 + y2) / 2) * height * precision_factor
    return UiTarsDesktopV001ScreenPoint(
        x=_js_round(x_scaled) / precision_factor,
        y=_js_round(y_scaled) / precision_factor,
    )


def ui_tars_desktop_v001_should_dispatch_to_device(
    action_type: str,
    *,
    aborted: bool = False,
) -> bool:
    """The 0.0.1 outer loop skips device.execute only for wait or an aborted run."""
    if not isinstance(action_type, str) or not action_type:
        raise ValueError("UI-TARS action_type is required")
    if type(aborted) is not bool:
        raise TypeError("UI-TARS aborted flag must be bool")
    return action_type != "wait" and not aborted


__all__ = [
    "UiTarsDesktopV001Action",
    "UiTarsDesktopV001Conversation",
    "UiTarsDesktopV001LoopState",
    "UiTarsDesktopV001ScreenPoint",
    "UiTarsDesktopV001Status",
    "UiTarsDesktopV001VlmView",
    "parse_ui_tars_desktop_v001_prediction",
    "project_ui_tars_desktop_v001_vlm_view",
    "ui_tars_desktop_v001_box_to_screen_point",
    "ui_tars_desktop_v001_should_dispatch_to_device",
]
