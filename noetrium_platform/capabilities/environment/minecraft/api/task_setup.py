from __future__ import annotations

"""Typed Minecraft task-setup contracts.

Benchmark authors describe *what* world mutation is required. Physical command
selection, credentials, retries and evidence belong to the Minecraft provider.
Raw scenario commands remain a compatibility escape hatch for legacy callers;
new benchmark assets should use ``world_ops``.
"""

from collections.abc import Mapping, Sequence
import re
from typing import Any

from noetrium_platform.foundation.kernel.kernel import canonical_digest, freeze_json

MINECRAFT_TASK_SETUP_SCHEMA_V1 = "noetrium.minecraft-task-setup.v1"
MINECRAFT_TASK_SETUP_SCHEMA_V2 = "noetrium.minecraft-task-setup.v2"
MINECRAFT_TASK_SETUP_SCHEMAS = frozenset({
    MINECRAFT_TASK_SETUP_SCHEMA_V1,
    MINECRAFT_TASK_SETUP_SCHEMA_V2,
})

_NAME = re.compile(r"[a-z0-9_]+")
_OP_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:-]*")


def _name(value: object, field: str) -> str:
    text = str(value).strip().removeprefix("minecraft:")
    if _NAME.fullmatch(text) is None:
        raise ValueError(f"Minecraft task setup {field} is invalid")
    return text


def _op_id(value: object) -> str:
    text = str(value).strip()
    if _OP_ID.fullmatch(text) is None:
        raise ValueError("Minecraft world operation id is invalid")
    return text


def _vec3(value: object, field: str) -> tuple[int, int, int]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"Minecraft task setup {field} must be an integer xyz sequence")
    values = tuple(value)
    if len(values) != 3 or any(type(item) is not int for item in values):
        raise ValueError(f"Minecraft task setup {field} must contain exactly three integers")
    if any(abs(item) > 30_000_000 for item in values):
        raise ValueError(f"Minecraft task setup {field} exceeds world coordinate bounds")
    return values  # type: ignore[return-value]


def minecraft_fill_world_op(
    operation_id: str,
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    block: str,
    *,
    anchor: str = "agent",
) -> Mapping[str, object]:
    if anchor not in {"agent", "world"}:
        raise ValueError("Minecraft fill anchor must be agent or world")
    return freeze_json({
        "operation_id": _op_id(operation_id),
        "kind": "fill",
        "anchor": anchor,
        "start": _vec3(start, "fill start"),
        "end": _vec3(end, "fill end"),
        "block": _name(block, "fill block"),
    })


def minecraft_set_block_world_op(
    operation_id: str,
    position: tuple[int, int, int],
    block: str,
    *,
    anchor: str = "agent",
) -> Mapping[str, object]:
    if anchor not in {"agent", "world"}:
        raise ValueError("Minecraft set_block anchor must be agent or world")
    return freeze_json({
        "operation_id": _op_id(operation_id),
        "kind": "set_block",
        "anchor": anchor,
        "position": _vec3(position, "set_block position"),
        "block": _name(block, "set_block block"),
    })


def minecraft_summon_world_op(
    operation_id: str,
    entity: str,
    position: tuple[int, int, int],
    *,
    anchor: str = "agent",
) -> Mapping[str, object]:
    if anchor not in {"agent", "world"}:
        raise ValueError("Minecraft summon anchor must be agent or world")
    return freeze_json({
        "operation_id": _op_id(operation_id),
        "kind": "summon",
        "anchor": anchor,
        "entity": _name(entity, "summon entity"),
        "position": _vec3(position, "summon position"),
    })


def minecraft_effect_world_op(
    operation_id: str,
    effect: str,
    *,
    duration_seconds: int,
    amplifier: int = 0,
    hide_particles: bool = True,
    target: str = "agent",
) -> Mapping[str, object]:
    if target != "agent":
        raise ValueError("Minecraft task setup effect currently supports only the agent target")
    if type(duration_seconds) is not int or duration_seconds <= 0:
        raise ValueError("Minecraft task setup effect duration must be positive integer seconds")
    if type(amplifier) is not int or amplifier < 0 or amplifier > 255:
        raise ValueError("Minecraft task setup effect amplifier is invalid")
    if type(hide_particles) is not bool:
        raise TypeError("Minecraft task setup effect hide_particles must be boolean")
    return freeze_json({
        "operation_id": _op_id(operation_id),
        "kind": "effect",
        "target": target,
        "effect": _name(effect, "effect"),
        "duration_seconds": duration_seconds,
        "amplifier": amplifier,
        "hide_particles": hide_particles,
    })


def normalize_minecraft_world_op(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("Minecraft world operation must be an object")
    kind = str(value.get("kind", "")).strip()
    operation_id = _op_id(value.get("operation_id", ""))
    if kind == "fill":
        return minecraft_fill_world_op(
            operation_id,
            _vec3(value.get("start"), "fill start"),
            _vec3(value.get("end"), "fill end"),
            str(value.get("block", "")),
            anchor=str(value.get("anchor", "agent")),
        )
    if kind == "set_block":
        return minecraft_set_block_world_op(
            operation_id,
            _vec3(value.get("position"), "set_block position"),
            str(value.get("block", "")),
            anchor=str(value.get("anchor", "agent")),
        )
    if kind == "summon":
        return minecraft_summon_world_op(
            operation_id,
            str(value.get("entity", "")),
            _vec3(value.get("position"), "summon position"),
            anchor=str(value.get("anchor", "agent")),
        )
    if kind == "effect":
        return minecraft_effect_world_op(
            operation_id,
            str(value.get("effect", "")),
            duration_seconds=int(value.get("duration_seconds", 0)),
            amplifier=int(value.get("amplifier", 0)),
            hide_particles=value.get("hide_particles", True),
            target=str(value.get("target", "agent")),
        )
    raise ValueError(f"unsupported Minecraft world operation kind: {kind!r}")


def normalize_minecraft_world_ops(value: object) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError("Minecraft world_ops must be a sequence")
    rows = tuple(normalize_minecraft_world_op(row) for row in value)
    ids = tuple(str(row["operation_id"]) for row in rows)
    if len(ids) != len(set(ids)):
        raise ValueError("Minecraft world operation ids must be unique")
    return rows


def minecraft_world_ops_digest(value: object) -> str:
    return canonical_digest(normalize_minecraft_world_ops(value))


__all__ = [
    "MINECRAFT_TASK_SETUP_SCHEMA_V1",
    "MINECRAFT_TASK_SETUP_SCHEMA_V2",
    "MINECRAFT_TASK_SETUP_SCHEMAS",
    "minecraft_effect_world_op",
    "minecraft_fill_world_op",
    "minecraft_set_block_world_op",
    "minecraft_summon_world_op",
    "minecraft_world_ops_digest",
    "normalize_minecraft_world_op",
    "normalize_minecraft_world_ops",
]
