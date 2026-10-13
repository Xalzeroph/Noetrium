from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re
from typing import Mapping

from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit

from .contracts import MinecraftJsonValue


_SCENARIO_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:-]*")
MINECRAFT_SCENARIO_TRAIT = "environment.minecraft-scenario"
MINECRAFT_SCENARIO_STEP_TRAIT = "environment.minecraft-scenario-step"
MINECRAFT_SCENARIO_COMMAND_MAX_LENGTH = 4096
MINECRAFT_SCENARIO_ASSERTION_MAX_LENGTH = 1024


def minecraft_scenario_step_unit(
    step_id: str,
    command: str,
    expected_response_contains: str,
    *,
    verification_command: str | None = None,
    timeout_s: float = 10.0,
) -> NoetriumUnit:
    if _SCENARIO_ID.fullmatch(step_id) is None:
        raise ValueError("Minecraft scenario step_id is invalid")
    for name, value in (
        ("command", command),
        ("expected_response_contains", expected_response_contains),
    ):
        if not value.strip() or "\x00" in value:
            raise ValueError(f"Minecraft scenario {name} is invalid")
    if (
        len(command) > MINECRAFT_SCENARIO_COMMAND_MAX_LENGTH
        or len(expected_response_contains) > MINECRAFT_SCENARIO_ASSERTION_MAX_LENGTH
    ):
        raise ValueError("Minecraft scenario command or assertion is too long")
    if verification_command is not None and (
        not verification_command.strip() or "\x00" in verification_command
    ):
        raise ValueError("Minecraft scenario verification_command is invalid")
    if (
        verification_command is not None
        and len(verification_command) > MINECRAFT_SCENARIO_COMMAND_MAX_LENGTH
    ):
        raise ValueError("Minecraft scenario verification_command is too long")
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, (int, float))
        or not math.isfinite(float(timeout_s))
        or not float(timeout_s) > 0
    ):
        raise ValueError("Minecraft scenario timeout_s must be finite and positive")
    return structure_unit(
        step_id,
        traits=(MINECRAFT_SCENARIO_STEP_TRAIT,),
        parameters={
            "command": command,
            "expected_response_contains": expected_response_contains,
            "verification_command": verification_command,
            "timeout_s": float(timeout_s),
        },
    )


def require_minecraft_scenario_step(value: NoetriumUnit) -> NoetriumUnit:
    if (
        type(value) is not NoetriumUnit
        or not value.has_trait(MINECRAFT_SCENARIO_STEP_TRAIT)
    ):
        raise TypeError("Minecraft scenario step must be NoetriumUnit")
    return value


def minecraft_scenario_step_id(value: NoetriumUnit) -> str:
    return require_minecraft_scenario_step(value).unit_id


def minecraft_scenario_step_command(value: NoetriumUnit) -> str:
    return str(require_minecraft_scenario_step(value).parameters["command"])


def minecraft_scenario_step_expected(value: NoetriumUnit) -> str:
    return str(
        require_minecraft_scenario_step(value).parameters[
            "expected_response_contains"
        ]
    )


def minecraft_scenario_step_verification(
    value: NoetriumUnit,
) -> str | None:
    raw = require_minecraft_scenario_step(value).parameters[
        "verification_command"
    ]
    return None if raw is None else str(raw)


def minecraft_scenario_step_timeout(value: NoetriumUnit) -> float:
    return float(require_minecraft_scenario_step(value).parameters["timeout_s"])


def minecraft_scenario_unit(
    scenario_id: str,
    generation: str,
    steps: tuple[NoetriumUnit, ...],
) -> NoetriumUnit:
    if (
        _SCENARIO_ID.fullmatch(scenario_id) is None
        or _SCENARIO_ID.fullmatch(generation) is None
    ):
        raise ValueError("Minecraft scenario identity is invalid")
    if type(steps) is not tuple or not steps:
        raise ValueError("Minecraft scenario requires at least one step")
    for step in steps:
        require_minecraft_scenario_step(step)
    step_ids = tuple(minecraft_scenario_step_id(step) for step in steps)
    if len(step_ids) != len(set(step_ids)):
        raise ValueError("Minecraft scenario step ids must be unique")
    return structure_unit(
        scenario_id,
        traits=(MINECRAFT_SCENARIO_TRAIT,),
        # Graph members are canonicalized as an unordered structural set.
        # Scenario execution order is semantic, so preserve it explicitly in
        # the Unit rather than depending on member storage order.
        parameters={
            "generation": generation,
            "step_order": step_ids,
        },
        members=steps,
    )


def require_minecraft_scenario(value: NoetriumUnit) -> NoetriumUnit:
    if (
        type(value) is not NoetriumUnit
        or not value.has_trait(MINECRAFT_SCENARIO_TRAIT)
    ):
        raise TypeError("Minecraft scenario must be NoetriumUnit")
    return value


def minecraft_scenario_id(value: NoetriumUnit) -> str:
    return require_minecraft_scenario(value).unit_id


def minecraft_scenario_generation(value: NoetriumUnit) -> str:
    return str(require_minecraft_scenario(value).parameters["generation"])


def minecraft_scenario_steps(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    scenario = require_minecraft_scenario(value)
    rows = tuple(scenario.members)
    by_id: dict[str, NoetriumUnit] = {}
    for row in rows:
        require_minecraft_scenario_step(row)
        step_id = minecraft_scenario_step_id(row)
        if step_id in by_id:
            raise ValueError("Minecraft scenario members contain duplicate step ids")
        by_id[step_id] = row
    raw_order = scenario.parameters.get("step_order")
    if not isinstance(raw_order, tuple) or any(
        type(step_id) is not str for step_id in raw_order
    ):
        raise ValueError("Minecraft scenario step_order is invalid")
    order = tuple(raw_order)
    if len(order) != len(set(order)) or set(order) != set(by_id):
        raise ValueError("Minecraft scenario step_order does not match members")
    return tuple(by_id[step_id] for step_id in order)


@dataclass(frozen=True, slots=True)
class MinecraftScenarioStepReceipt:
    step_id: str
    step_digest: str
    command_evidence_ref: str
    command_response_sha256: str
    verification_evidence_ref: str
    verification_response_sha256: str

    def __post_init__(self) -> None:
        if _SCENARIO_ID.fullmatch(self.step_id) is None:
            raise ValueError("Minecraft scenario receipt step_id is invalid")
        if (
            not self.command_evidence_ref.strip()
            or not self.verification_evidence_ref.strip()
        ):
            raise ValueError("Minecraft scenario receipt evidence is incomplete")
        for value in (
            self.step_digest,
            self.command_response_sha256,
            self.verification_response_sha256,
        ):
            if len(value) != 64 or any(
                char not in "0123456789abcdef" for char in value.lower()
            ):
                raise ValueError("Minecraft scenario receipt digest is invalid")


@dataclass(frozen=True, slots=True)
class MinecraftScenarioReceipt:
    scenario_id: str
    generation: str
    scenario_digest: str
    steps: tuple[MinecraftScenarioStepReceipt, ...]

    def __post_init__(self) -> None:
        if (
            _SCENARIO_ID.fullmatch(self.scenario_id) is None
            or _SCENARIO_ID.fullmatch(self.generation) is None
        ):
            raise ValueError("Minecraft scenario receipt identity is invalid")
        if len(self.scenario_digest) != 64 or any(
            char not in "0123456789abcdef"
            for char in self.scenario_digest.lower()
        ):
            raise ValueError("Minecraft scenario receipt digest is invalid")
        if not self.steps:
            raise ValueError("Minecraft scenario receipt requires step evidence")


def minecraft_scenario_from_mapping(
    raw: Mapping[str, MinecraftJsonValue],
) -> NoetriumUnit:
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, (list, tuple)):
        raise ValueError("Minecraft scenario manifest requires a steps list")
    steps: list[NoetriumUnit] = []
    for index, value in enumerate(raw_steps):
        if not isinstance(value, Mapping):
            raise ValueError(f"Minecraft scenario step {index} must be a mapping")
        verification = value.get("verification_command")
        steps.append(
            minecraft_scenario_step_unit(
                step_id=str(value.get("step_id", "")),
                command=str(value.get("command", "")),
                expected_response_contains=str(
                    value.get("expected_response_contains", "")
                ),
                verification_command=(
                    str(verification) if verification is not None else None
                ),
                timeout_s=float(value.get("timeout_s", 10.0)),
            )
        )
    return minecraft_scenario_unit(
        str(raw.get("scenario_id", "")),
        str(raw.get("generation", "")),
        tuple(steps),
    )


def minecraft_response_sha256(response: str) -> str:
    return hashlib.sha256(response.encode("utf-8")).hexdigest()


__all__ = [
    "MINECRAFT_SCENARIO_ASSERTION_MAX_LENGTH",
    "MINECRAFT_SCENARIO_COMMAND_MAX_LENGTH",
    "MINECRAFT_SCENARIO_STEP_TRAIT",
    "MINECRAFT_SCENARIO_TRAIT",
    "MinecraftScenarioReceipt",
    "MinecraftScenarioStepReceipt",
    "minecraft_response_sha256",
    "minecraft_scenario_from_mapping",
    "minecraft_scenario_generation",
    "minecraft_scenario_id",
    "minecraft_scenario_step_command",
    "minecraft_scenario_step_expected",
    "minecraft_scenario_step_id",
    "minecraft_scenario_step_timeout",
    "minecraft_scenario_step_unit",
    "minecraft_scenario_step_verification",
    "minecraft_scenario_steps",
    "minecraft_scenario_unit",
    "require_minecraft_scenario",
    "require_minecraft_scenario_step",
]
