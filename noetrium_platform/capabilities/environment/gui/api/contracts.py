from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from noetrium_platform.capabilities.environment.api.semantics import (
    environment_capabilities,
    environment_unit,
    require_environment_unit,
)
from noetrium_platform.foundation.kernel.kernel import JsonValue, freeze_json
from noetrium_platform.foundation.kernel.structure import NoetriumUnit


class GuiActionKind(StrEnum):
    CLICK = "click"
    TYPE = "type"
    KEY = "key"
    SCROLL = "scroll"
    DRAG = "drag"
    WAIT = "wait"


def gui_context_policy(
    *,
    max_accessibility_chars: int = 40_000,
    max_accessibility_nodes: int = 1_024,
    max_history_turns: int = 3,
    include_screenshot: bool = True,
    active_window_only: bool = False,
) -> Mapping[str, JsonValue]:
    for name, value, minimum in (
        ("max_accessibility_chars", max_accessibility_chars, 1_000),
        ("max_accessibility_nodes", max_accessibility_nodes, 1),
        ("max_history_turns", max_history_turns, 0),
    ):
        if type(value) is not int or value < minimum:
            raise ValueError(f"GUI context policy {name} is invalid")
    for name, value in (
        ("include_screenshot", include_screenshot),
        ("active_window_only", active_window_only),
    ):
        if type(value) is not bool:
            raise TypeError(f"GUI context policy {name} must be boolean")
    return freeze_json({
        "max_accessibility_chars": max_accessibility_chars,
        "max_accessibility_nodes": max_accessibility_nodes,
        "max_history_turns": max_history_turns,
        "include_screenshot": include_screenshot,
        "active_window_only": active_window_only,
    })


def gui_environment_unit(
    environment_id: str,
    revision: str,
    *,
    viewport: tuple[int, int] = (0, 0),
    supports_accessibility: bool = False,
    supported_actions: tuple[GuiActionKind, ...] = (),
    metadata: Mapping[str, JsonValue] | None = None,
    context_policy: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    if len(viewport) != 2 or any(type(v) is not int or v < 0 for v in viewport):
        raise ValueError("GUI viewport must contain two non-negative integers")
    if type(supports_accessibility) is not bool:
        raise TypeError("GUI accessibility flag must be boolean")
    if type(supported_actions) is not tuple or any(
        not isinstance(item, GuiActionKind) for item in supported_actions
    ):
        raise TypeError("GUI actions must use GuiActionKind tuple")
    if len(supported_actions) != len(set(supported_actions)):
        raise ValueError("GUI actions must be unique")
    policy = gui_context_policy() if context_policy is None else freeze_json(context_policy)
    return environment_unit(
        environment_id,
        category="gui",
        revision=revision,
        capabilities=tuple(item.value for item in supported_actions) or ("observe",),
        parameters={
            "viewport": viewport,
            "supports_accessibility": supports_accessibility,
            "metadata": freeze_json({} if metadata is None else metadata),
            "context_policy": policy,
        },
    )


def require_gui_environment(value: NoetriumUnit) -> NoetriumUnit:
    value = require_environment_unit(value)
    if value.parameters["category"] != "gui":
        raise TypeError("GUI environment Unit must have category='gui'")
    return value


def gui_environment_context_policy(value: NoetriumUnit) -> Mapping[str, JsonValue]:
    return require_gui_environment(value).parameters["context_policy"]


def gui_environment_supported_actions(value: NoetriumUnit) -> tuple[GuiActionKind, ...]:
    return tuple(
        GuiActionKind(item)
        for item in environment_capabilities(require_gui_environment(value))
        if item in {kind.value for kind in GuiActionKind}
    )


__all__ = [
    "GuiActionKind",
    "gui_context_policy",
    "gui_environment_context_policy",
    "gui_environment_supported_actions",
    "gui_environment_unit",
    "require_gui_environment",
]
