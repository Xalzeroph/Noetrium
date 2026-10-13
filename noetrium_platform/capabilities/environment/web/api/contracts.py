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


class WebActionKind(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    SCROLL = "scroll"
    SUBMIT = "submit"
    BACK = "back"
    WAIT = "wait"


def web_context_policy(
    *,
    max_page_text_chars: int = 24_000,
    max_dom_chars: int = 32_000,
    max_accessibility_chars: int = 40_000,
    max_interactive_nodes: int = 512,
    max_history_turns: int = 4,
    include_screenshot: bool = True,
) -> Mapping[str, JsonValue]:
    for name, value, minimum in (
        ("max_page_text_chars", max_page_text_chars, 1_000),
        ("max_dom_chars", max_dom_chars, 1_000),
        ("max_accessibility_chars", max_accessibility_chars, 1_000),
        ("max_interactive_nodes", max_interactive_nodes, 1),
        ("max_history_turns", max_history_turns, 0),
    ):
        if type(value) is not int or value < minimum:
            raise ValueError(f"web context policy {name} is invalid")
    if type(include_screenshot) is not bool:
        raise TypeError("web context policy include_screenshot must be boolean")
    return freeze_json({
        "max_page_text_chars": max_page_text_chars,
        "max_dom_chars": max_dom_chars,
        "max_accessibility_chars": max_accessibility_chars,
        "max_interactive_nodes": max_interactive_nodes,
        "max_history_turns": max_history_turns,
        "include_screenshot": include_screenshot,
    })


def web_environment_unit(
    environment_id: str,
    revision: str,
    *,
    origin: str = "",
    supports_dom: bool = True,
    supported_actions: tuple[WebActionKind, ...] = (),
    metadata: Mapping[str, JsonValue] | None = None,
    context_policy: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    if type(supports_dom) is not bool:
        raise TypeError("Web DOM flag must be boolean")
    if type(supported_actions) is not tuple or any(
        not isinstance(item, WebActionKind) for item in supported_actions
    ):
        raise TypeError("Web actions must use WebActionKind tuple")
    if len(supported_actions) != len(set(supported_actions)):
        raise ValueError("Web actions must be unique")
    policy = web_context_policy() if context_policy is None else freeze_json(context_policy)
    return environment_unit(
        environment_id,
        category="web",
        revision=revision,
        capabilities=tuple(item.value for item in supported_actions) or ("observe",),
        parameters={
            "origin": origin,
            "supports_dom": supports_dom,
            "metadata": freeze_json({} if metadata is None else metadata),
            "context_policy": policy,
        },
    )


def require_web_environment(value: NoetriumUnit) -> NoetriumUnit:
    value = require_environment_unit(value)
    if value.parameters["category"] != "web":
        raise TypeError("Web environment Unit must have category='web'")
    return value


def web_environment_context_policy(value: NoetriumUnit) -> Mapping[str, JsonValue]:
    return require_web_environment(value).parameters["context_policy"]


def web_environment_supported_actions(value: NoetriumUnit) -> tuple[WebActionKind, ...]:
    return tuple(
        WebActionKind(item)
        for item in environment_capabilities(require_web_environment(value))
        if item in {kind.value for kind in WebActionKind}
    )


__all__ = [
    "WebActionKind",
    "require_web_environment",
    "web_context_policy",
    "web_environment_context_policy",
    "web_environment_supported_actions",
    "web_environment_unit",
]
