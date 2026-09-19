from __future__ import annotations

import re
from dataclasses import dataclass

from noetrium_platform.capabilities.environment.composition import (
    environment_action_capability_payload,
)
from noetrium_platform.foundation.kernel.kernel import JsonInput

from .fidelity import WEBVOYAGER_FIDELITY

_CLICK = re.compile(r"^Click\s*\[(?P<label>\d+)\]\s*$", re.IGNORECASE)
_TYPE = re.compile(
    r"^Type\s*\[(?P<label>\d+)\]\s*;\s*(?P<content>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_SCROLL = re.compile(
    r"^Scroll\s*\[(?P<target>\d+|WINDOW)\]\s*;\s*"
    r"(?P<direction>up|down)\s*$",
    re.IGNORECASE,
)
_ANSWER = re.compile(r"^ANSWER\s*;\s*(?P<content>.+)$", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True, slots=True)
class WebVoyagerAction:
    thought: str
    kind: str
    target: int | str | None = None
    content: str = ""

    def __post_init__(self) -> None:
        if type(self.thought) is not str:
            raise TypeError("WebVoyager thought must be text")
        if self.kind not in WEBVOYAGER_FIDELITY.action_grammar:
            raise ValueError(f"unsupported WebVoyager action: {self.kind!r}")
        if self.kind in {"Click", "Type"}:
            if type(self.target) is not int or self.target < 0:
                raise ValueError(f"WebVoyager {self.kind} requires numerical label")
        if self.kind == "Scroll":
            if not (
                type(self.target) is int and self.target >= 0
                or self.target == "WINDOW"
            ):
                raise ValueError("WebVoyager Scroll requires label or WINDOW")
            if self.content not in {"up", "down"}:
                raise ValueError("WebVoyager Scroll direction must be up/down")
        if self.kind in {"Type", "ANSWER"} and not self.content.strip():
            raise ValueError(f"WebVoyager {self.kind} requires content")

    @property
    def terminal(self) -> bool:
        return self.kind == "ANSWER"

    def as_row(self) -> dict[str, JsonInput]:
        return {
            "thought": self.thought,
            "kind": self.kind,
            "target": self.target,
            "content": self.content,
        }

    def environment_payload(self) -> dict[str, JsonInput]:
        if self.terminal:
            raise ValueError("terminal WebVoyager answer is not an environment action")
        if self.kind == "Click":
            return environment_action_capability_payload(
                "click",
                {"element_label": self.target},
            )
        if self.kind == "Type":
            return environment_action_capability_payload(
                "type",
                {
                    "element_label": self.target,
                    "text": self.content,
                    "submit": WEBVOYAGER_FIDELITY.type_action_auto_enter,
                },
            )
        if self.kind == "Scroll":
            return environment_action_capability_payload(
                "scroll",
                {
                    "target": self.target,
                    "direction": self.content,
                },
            )
        if self.kind == "Wait":
            return environment_action_capability_payload(
                "wait",
                {"seconds": WEBVOYAGER_FIDELITY.wait_seconds},
            )
        if self.kind == "GoBack":
            return environment_action_capability_payload("back", {})
        if self.kind == "Google":
            return environment_action_capability_payload(
                "navigate",
                {"url": "https://www.google.com/"},
            )
        raise ValueError(f"WebVoyager action has no environment mapping: {self.kind}")


def parse_webvoyager_response(text: str) -> WebVoyagerAction:
    if type(text) is not str or not text.strip():
        raise ValueError("WebVoyager model response must be non-empty text")
    thought_prefix = "Thought:"
    action_prefix = "Action:"
    thought_index = text.find(thought_prefix)
    action_index = text.find(action_prefix)
    if thought_index < 0 or action_index < 0 or action_index <= thought_index:
        raise ValueError(
            "WebVoyager response must contain Thought then Action"
        )
    thought = text[
        thought_index + len(thought_prefix) : action_index
    ].strip()
    action = text[action_index + len(action_prefix) :].strip()
    if not thought:
        raise ValueError("WebVoyager Thought must be non-empty")

    match = _CLICK.fullmatch(action)
    if match:
        return WebVoyagerAction(thought, "Click", int(match.group("label")))
    match = _TYPE.fullmatch(action)
    if match:
        return WebVoyagerAction(
            thought,
            "Type",
            int(match.group("label")),
            match.group("content").strip(),
        )
    match = _SCROLL.fullmatch(action)
    if match:
        raw_target = match.group("target")
        target: int | str = (
            "WINDOW"
            if raw_target.upper() == "WINDOW"
            else int(raw_target)
        )
        return WebVoyagerAction(
            thought,
            "Scroll",
            target,
            match.group("direction").lower(),
        )
    if action.lower() == "wait":
        return WebVoyagerAction(thought, "Wait")
    if action.lower() == "goback":
        return WebVoyagerAction(thought, "GoBack")
    if action.lower() == "google":
        return WebVoyagerAction(thought, "Google")
    match = _ANSWER.fullmatch(action)
    if match:
        return WebVoyagerAction(
            thought,
            "ANSWER",
            None,
            match.group("content").strip(),
        )
    raise ValueError("WebVoyager Action does not match released grammar")


__all__ = ["WebVoyagerAction", "parse_webvoyager_response"]
