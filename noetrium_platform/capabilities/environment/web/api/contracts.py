from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest, freeze_json, thaw_json


class WebActionKind(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    SCROLL = "scroll"
    SUBMIT = "submit"
    BACK = "back"
    WAIT = "wait"


@dataclass(frozen=True, slots=True)
class WebContextPolicy:
    """Provider-side bounds for the LLM-visible browser observation."""

    max_page_text_chars: int = 24_000
    max_dom_chars: int = 32_000
    max_accessibility_chars: int = 40_000
    max_interactive_nodes: int = 512
    max_history_turns: int = 4
    include_screenshot: bool = True

    def __post_init__(self) -> None:
        for name, value, minimum in (
            ("max_page_text_chars", self.max_page_text_chars, 1_000),
            ("max_dom_chars", self.max_dom_chars, 1_000),
            ("max_accessibility_chars", self.max_accessibility_chars, 1_000),
            ("max_interactive_nodes", self.max_interactive_nodes, 1),
            ("max_history_turns", self.max_history_turns, 0),
        ):
            if type(value) is not int or value < minimum:
                raise ValueError(f"web context policy {name} is invalid")
        if type(self.include_screenshot) is not bool:
            raise TypeError("web context policy include_screenshot must be boolean")

    def record(self) -> dict[str, JsonValue]:
        return {
            "max_page_text_chars": self.max_page_text_chars,
            "max_dom_chars": self.max_dom_chars,
            "max_accessibility_chars": self.max_accessibility_chars,
            "max_interactive_nodes": self.max_interactive_nodes,
            "max_history_turns": self.max_history_turns,
            "include_screenshot": self.include_screenshot,
        }


@dataclass(frozen=True, slots=True)
class WebEnvironmentSpec:
    environment_id: str
    revision: str
    origin: str = ""
    supports_dom: bool = True
    supported_actions: tuple[WebActionKind, ...] = ()
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    context_policy: WebContextPolicy = field(default_factory=WebContextPolicy)

    def __post_init__(self) -> None:
        if not self.environment_id.strip() or not self.revision.strip():
            raise ValueError("Web environment identity is required")
        if not isinstance(self.supports_dom, bool):
            raise TypeError("Web DOM flag must be boolean")
        if any(not isinstance(item, WebActionKind) for item in self.supported_actions):
            raise TypeError("Web actions must use WebActionKind")
        if len(self.supported_actions) != len(set(self.supported_actions)):
            raise ValueError("Web actions must be unique")
        object.__setattr__(self, "metadata", freeze_json(self.metadata or {}))

    @property
    def spec_digest(self) -> str:
        return canonical_digest({
            "environment_id": self.environment_id, "revision": self.revision,
            "origin": self.origin, "supports_dom": self.supports_dom,
            "supported_actions": [item.value for item in self.supported_actions],
            "metadata": thaw_json(self.metadata),
            "context_policy": self.context_policy.record(),
        })


__all__ = ["WebActionKind", "WebContextPolicy", "WebEnvironmentSpec"]
