from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re
from typing import Mapping

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .contracts import MinecraftJsonValue


_SCENARIO_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:-]*")


@dataclass(frozen=True, slots=True)
class MinecraftScenarioStep:
    """One fail-closed source-world mutation and its observable assertion."""

    step_id: str
    command: str
    expected_response_contains: str
    verification_command: str | None = None
    timeout_s: float = 10.0

    def __post_init__(self) -> None:
        if not _SCENARIO_ID.fullmatch(self.step_id):
            raise ValueError("Minecraft scenario step_id is invalid")
        for name, value in (
            ("command", self.command),
            ("expected_response_contains", self.expected_response_contains),
        ):
            if not value.strip() or "\x00" in value:
                raise ValueError(f"Minecraft scenario {name} is invalid")
        if len(self.command) > 4096 or len(self.expected_response_contains) > 1024:
            raise ValueError("Minecraft scenario command or assertion is too long")
        if self.verification_command is not None and (
            not self.verification_command.strip() or "\x00" in self.verification_command
        ):
            raise ValueError("Minecraft scenario verification_command is invalid")
        if self.verification_command is not None and len(self.verification_command) > 4096:
            raise ValueError("Minecraft scenario verification_command is too long")
        if not isinstance(self.timeout_s, (int, float)) or isinstance(self.timeout_s, bool):
            raise TypeError("Minecraft scenario timeout_s must be numeric")
        if not math.isfinite(float(self.timeout_s)) or not 0 < self.timeout_s <= 120:
            raise ValueError("Minecraft scenario timeout_s must be in (0, 120]")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class MinecraftScenarioSpec:
    """Immutable, ordered source-world fixture independent of any experiment."""

    scenario_id: str
    generation: str
    steps: tuple[MinecraftScenarioStep, ...]

    def __post_init__(self) -> None:
        if not _SCENARIO_ID.fullmatch(self.scenario_id) or not _SCENARIO_ID.fullmatch(self.generation):
            raise ValueError("Minecraft scenario identity is invalid")
        if not self.steps:
            raise ValueError("Minecraft scenario requires at least one step")
        if len(self.steps) > 256:
            raise ValueError("Minecraft scenario cannot exceed 256 steps")
        step_ids = tuple(step.step_id for step in self.steps)
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Minecraft scenario step ids must be unique")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class MinecraftScenarioStepReceipt:
    step_id: str
    step_digest: str
    command_evidence_ref: str
    command_response_sha256: str
    verification_evidence_ref: str
    verification_response_sha256: str

    def __post_init__(self) -> None:
        if not _SCENARIO_ID.fullmatch(self.step_id):
            raise ValueError("Minecraft scenario receipt step_id is invalid")
        if not self.command_evidence_ref.strip() or not self.verification_evidence_ref.strip():
            raise ValueError("Minecraft scenario receipt evidence is incomplete")
        for value in (
            self.step_digest,
            self.command_response_sha256,
            self.verification_response_sha256,
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
                raise ValueError("Minecraft scenario receipt digest is invalid")


@dataclass(frozen=True, slots=True)
class MinecraftScenarioReceipt:
    scenario_id: str
    generation: str
    scenario_digest: str
    steps: tuple[MinecraftScenarioStepReceipt, ...]

    def __post_init__(self) -> None:
        if not _SCENARIO_ID.fullmatch(self.scenario_id) or not _SCENARIO_ID.fullmatch(self.generation):
            raise ValueError("Minecraft scenario receipt identity is invalid")
        if len(self.scenario_digest) != 64 or any(
            char not in "0123456789abcdef" for char in self.scenario_digest.lower()
        ):
            raise ValueError("Minecraft scenario receipt digest is invalid")
        if not self.steps:
            raise ValueError("Minecraft scenario receipt requires step evidence")

    def digest(self) -> str:
        return canonical_digest(self)


def minecraft_scenario_from_mapping(
    raw: Mapping[str, MinecraftJsonValue],
) -> MinecraftScenarioSpec:
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, (list, tuple)):
        raise ValueError("Minecraft scenario manifest requires a steps list")
    steps: list[MinecraftScenarioStep] = []
    for index, value in enumerate(raw_steps):
        if not isinstance(value, Mapping):
            raise ValueError(f"Minecraft scenario step {index} must be a mapping")
        verification = value.get("verification_command")
        steps.append(
            MinecraftScenarioStep(
                step_id=str(value.get("step_id", "")),
                command=str(value.get("command", "")),
                expected_response_contains=str(value.get("expected_response_contains", "")),
                verification_command=(str(verification) if verification is not None else None),
                timeout_s=float(value.get("timeout_s", 10.0)),
            )
        )
    return MinecraftScenarioSpec(
        scenario_id=str(raw.get("scenario_id", "")),
        generation=str(raw.get("generation", "")),
        steps=tuple(steps),
    )


def minecraft_response_sha256(response: str) -> str:
    return hashlib.sha256(response.encode("utf-8")).hexdigest()


__all__ = [
    "MinecraftScenarioReceipt",
    "MinecraftScenarioSpec",
    "MinecraftScenarioStep",
    "MinecraftScenarioStepReceipt",
    "minecraft_response_sha256",
    "minecraft_scenario_from_mapping",
]
