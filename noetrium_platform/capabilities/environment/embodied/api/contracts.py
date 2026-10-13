from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import sha256_bytes
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonInput,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    thaw_json,
)


def _text(name: str, value: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


class EmbodimentKind(StrEnum):
    ROBOT_ARM = "robot_arm"
    MOBILE_MANIPULATOR = "mobile_manipulator"
    HUMANOID = "humanoid"
    QUADRUPED = "quadruped"
    SIMULATED = "simulated"
    OTHER = "other"


class SensorModality(StrEnum):
    RGB = "rgb"
    DEPTH = "depth"
    RGBD = "rgbd"
    TACTILE = "tactile"
    PROPRIOCEPTION = "proprioception"
    AUDIO = "audio"
    FORCE_TORQUE = "force_torque"
    EVENT = "event"
    OTHER = "other"


class ActionKind(StrEnum):
    JOINT = "joint"
    CARTESIAN = "cartesian"
    GRIPPER = "gripper"
    BASE = "base"
    WAYPOINT = "waypoint"
    OTHER = "other"


class EmbodiedEventProjectionKind(StrEnum):
    EPISODE_START = "episode_start"
    OBSERVATION = "observation"
    ACTION_COMMAND = "action_command"
    ACTION_RESULT = "action_result"
    REWARD = "reward"
    CHECKPOINT = "checkpoint"
    TERMINATION = "termination"
    ERROR = "error"


SENSOR_TRAIT = "environment.sensor"
ACTION_TRAIT = "environment.action"
EMBODIMENT_TRAIT = "environment.embodiment"
EPISODE_TRAIT = "environment.episode"


def sensor_unit(
    sensor_id: str,
    modality: SensorModality | str,
    frame_id: str,
    dtype: str,
    shape: tuple[int, ...] = (),
    rate_hz: float = 0.0,
    unit: str = "",
    calibration_digest: str = "",
    metadata: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    for name, value in (("sensor_id", sensor_id), ("frame_id", frame_id), ("dtype", dtype)):
        _text(name, value)
    if any(type(item) is not int or item < 0 for item in shape):
        raise ValueError("sensor shape must contain non-negative integers")
    if isinstance(rate_hz, bool) or not isinstance(rate_hz, (int, float)) or float(rate_hz) < 0:
        raise ValueError("sensor rate_hz must be non-negative")
    modality_value = modality.value if isinstance(modality, SensorModality) else modality
    if type(modality_value) is not str or not modality_value.strip():
        raise TypeError("sensor modality must be non-empty")
    return structure_unit(
        sensor_id,
        traits=(SENSOR_TRAIT,),
        parameters={
            "modality": modality_value,
            "frame_id": frame_id,
            "dtype": dtype,
            "shape": shape,
            "rate_hz": float(rate_hz),
            "unit": unit,
            "calibration_digest": calibration_digest,
            "metadata": freeze_json({} if metadata is None else metadata),
        },
    )


def require_sensor(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(SENSOR_TRAIT):
        raise TypeError("sensor must be environment.sensor NoetriumUnit")
    return value


def sensor_record(value: NoetriumUnit) -> JsonObject:
    value = require_sensor(value)
    return {
        "sensor_id": value.unit_id,
        "modality": value.parameters["modality"],
        "frame_id": value.parameters["frame_id"],
        "dtype": value.parameters["dtype"],
        "shape": list(value.parameters["shape"]),
        "rate_hz": value.parameters["rate_hz"],
        "unit": value.parameters["unit"],
        "calibration_digest": value.parameters["calibration_digest"],
        "metadata": thaw_json(value.parameters["metadata"]),
    }


def action_spec_unit(
    action_id: str,
    kind: ActionKind,
    dimensions: int,
    dtype: str = "float32",
    rate_hz: float = 0.0,
    unit: str = "",
    bounds: tuple[tuple[float, float], ...] = (),
    metadata: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    _text("action_id", action_id)
    _text("dtype", dtype)
    if not isinstance(kind, ActionKind):
        raise TypeError("action kind must use ActionKind")
    if type(dimensions) is not int or dimensions < 0:
        raise ValueError("action dimensions must be non-negative")
    if isinstance(rate_hz, bool) or not isinstance(rate_hz, (int, float)) or float(rate_hz) < 0:
        raise ValueError("action rate_hz must be non-negative")
    if bounds and len(bounds) != dimensions:
        raise ValueError("action bounds must match dimensions")
    if any(lower > upper for lower, upper in bounds):
        raise ValueError("action bounds must be ordered")
    return structure_unit(
        action_id,
        traits=(ACTION_TRAIT,),
        parameters={
            "kind": kind.value,
            "dimensions": dimensions,
            "dtype": dtype,
            "rate_hz": float(rate_hz),
            "unit": unit,
            "bounds": bounds,
            "metadata": freeze_json({} if metadata is None else metadata),
        },
    )


def require_action_spec(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(ACTION_TRAIT):
        raise TypeError("action spec must be environment.action NoetriumUnit")
    return value


def action_spec_record(value: NoetriumUnit) -> JsonObject:
    value = require_action_spec(value)
    return {
        "action_id": value.unit_id,
        "kind": value.parameters["kind"],
        "dimensions": value.parameters["dimensions"],
        "dtype": value.parameters["dtype"],
        "rate_hz": value.parameters["rate_hz"],
        "unit": value.parameters["unit"],
        "bounds": [list(item) for item in value.parameters["bounds"]],
        "metadata": thaw_json(value.parameters["metadata"]),
    }


def embodiment_unit(
    embodiment_id: str,
    revision: str,
    kind: EmbodimentKind,
    sensors: tuple[NoetriumUnit, ...] = (),
    actions: tuple[NoetriumUnit, ...] = (),
    root_frame: str = "world",
    metadata: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    _text("embodiment_id", embodiment_id)
    _text("revision", revision)
    _text("root_frame", root_frame)
    if not isinstance(kind, EmbodimentKind):
        raise TypeError("embodiment kind must use EmbodimentKind")
    if type(sensors) is not tuple or type(actions) is not tuple:
        raise TypeError("embodiment sensors/actions must be Unit tuples")
    for row in sensors:
        require_sensor(row)
    for row in actions:
        require_action_spec(row)
    if len({row.unit_id for row in sensors}) != len(sensors):
        raise ValueError("embodiment sensor ids must be unique")
    if len({row.unit_id for row in actions}) != len(actions):
        raise ValueError("embodiment action ids must be unique")
    return structure_unit(
        embodiment_id,
        traits=(EMBODIMENT_TRAIT,),
        parameters={
            "revision": revision,
            "kind": kind.value,
            "root_frame": root_frame,
            "metadata": freeze_json({} if metadata is None else metadata),
        },
        members=tuple(sorted((*sensors, *actions), key=lambda row: row.unit_id)),
    )


def require_embodiment(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(EMBODIMENT_TRAIT):
        raise TypeError("embodiment must be environment.embodiment NoetriumUnit")
    return value


def embodiment_id(value: NoetriumUnit) -> str:
    return require_embodiment(value).unit_id


def embodiment_record(value: NoetriumUnit) -> JsonObject:
    value = require_embodiment(value)
    sensors = tuple(row for row in value.members if row.has_trait(SENSOR_TRAIT))
    actions = tuple(row for row in value.members if row.has_trait(ACTION_TRAIT))
    return {
        "embodiment_id": value.unit_id,
        "revision": value.parameters["revision"],
        "kind": value.parameters["kind"],
        "sensors": [sensor_record(row) for row in sensors],
        "actions": [action_spec_record(row) for row in actions],
        "root_frame": value.parameters["root_frame"],
        "metadata": thaw_json(value.parameters["metadata"]),
    }


def embodiment_digest(value: NoetriumUnit) -> str:
    return require_embodiment(value).unit_digest


def embodiment_sensors(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    value = require_embodiment(value)
    return tuple(row for row in value.members if row.has_trait(SENSOR_TRAIT))


def embodiment_actions(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    value = require_embodiment(value)
    return tuple(row for row in value.members if row.has_trait(ACTION_TRAIT))


def episode_unit(
    episode_id: str,
    environment_id: str,
    embodiment_id_value: str,
    task_id: str,
    seed: int | None = None,
    scenario_id: str = "",
    policy_id: str = "",
    metadata: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    for name, value in (
        ("episode_id", episode_id),
        ("environment_id", environment_id),
        ("embodiment_id", embodiment_id_value),
        ("task_id", task_id),
    ):
        _text(name, value)
    if seed is not None and type(seed) is not int:
        raise TypeError("episode seed must be integer or None")
    return structure_unit(
        episode_id,
        traits=(EPISODE_TRAIT,),
        parameters={
            "environment_id": environment_id,
            "embodiment_id": embodiment_id_value,
            "task_id": task_id,
            "seed": seed,
            "scenario_id": scenario_id,
            "policy_id": policy_id,
            "metadata": freeze_json({} if metadata is None else metadata),
        },
    )


def require_episode(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(EPISODE_TRAIT):
        raise TypeError("episode must be environment.episode NoetriumUnit")
    return value


def episode_id(value: NoetriumUnit) -> str:
    return require_episode(value).unit_id


def episode_environment_id(value: NoetriumUnit) -> str:
    return str(require_episode(value).parameters["environment_id"])


def episode_embodiment_id(value: NoetriumUnit) -> str:
    return str(require_episode(value).parameters["embodiment_id"])


def episode_task_id(value: NoetriumUnit) -> str:
    return str(require_episode(value).parameters["task_id"])


def episode_record(value: NoetriumUnit) -> JsonObject:
    value = require_episode(value)
    return {
        "episode_id": value.unit_id,
        "environment_id": value.parameters["environment_id"],
        "embodiment_id": value.parameters["embodiment_id"],
        "task_id": value.parameters["task_id"],
        "seed": value.parameters["seed"],
        "scenario_id": value.parameters["scenario_id"],
        "policy_id": value.parameters["policy_id"],
        "metadata": thaw_json(value.parameters["metadata"]),
    }


def episode_digest(value: NoetriumUnit) -> str:
    return require_episode(value).unit_digest


@dataclass(frozen=True, slots=True)
class EmbodiedActionCommand:
    command_id: str
    episode_id: str
    action_id: str
    sequence: int
    raw_payload: bytes
    normalized_payload: JsonInput
    issued_at_ns: int
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (("command_id", self.command_id), ("episode_id", self.episode_id), ("action_id", self.action_id)):
            _text(name, value)
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("action sequence must be positive")
        if type(self.raw_payload) is not bytes:
            raise TypeError("action raw_payload must be exact bytes")
        if type(self.issued_at_ns) is not int or self.issued_at_ns <= 0:
            raise ValueError("action issued_at_ns must be positive")
        object.__setattr__(self, "normalized_payload", freeze_json(self.normalized_payload))
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    @property
    def raw_payload_sha256(self) -> str:
        return sha256_bytes(self.raw_payload)



@dataclass(frozen=True, slots=True)
class EmbodiedEventProjection:
    event_id: str
    episode_id: str
    sequence: int
    kind: EmbodiedEventProjectionKind
    event_time_ns: int
    raw_payload: bytes
    normalized_payload: JsonObject
    source_id: str
    embodiment_id: str
    environment_id: str
    task_id: str
    step_index: int | None = None
    sensor_id: str = ""
    action_id: str = ""
    status: str = "ok"
    outcome: str | None = None
    terminated: bool = False
    truncated: bool = False
    dimensions: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("event_id", self.event_id),
            ("episode_id", self.episode_id),
            ("source_id", self.source_id),
            ("embodiment_id", self.embodiment_id),
            ("environment_id", self.environment_id),
            ("task_id", self.task_id),
            ("status", self.status),
        ):
            _text(name, value)
        if not isinstance(self.kind, EmbodiedEventProjectionKind):
            raise TypeError("event kind must use EmbodiedEventProjectionKind")
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("event sequence must be positive")
        if type(self.event_time_ns) is not int or self.event_time_ns <= 0:
            raise ValueError("event_time_ns must be positive")
        if type(self.raw_payload) is not bytes:
            raise TypeError("event raw_payload must be exact bytes")
        if self.step_index is not None and (type(self.step_index) is not int or self.step_index < 0):
            raise ValueError("event step_index must be non-negative or None")
        if type(self.terminated) is not bool or type(self.truncated) is not bool:
            raise TypeError("event terminated/truncated must be booleans")
        object.__setattr__(self, "normalized_payload", freeze_json(self.normalized_payload))
        object.__setattr__(self, "dimensions", freeze_json(self.dimensions))

    @property
    def raw_payload_sha256(self) -> str:
        return sha256_bytes(self.raw_payload)

    @property
    def event_digest(self) -> str:
        return canonical_digest({
            "event_id": self.event_id,
            "episode_id": self.episode_id,
            "sequence": self.sequence,
            "kind": self.kind.value,
            "event_time_ns": self.event_time_ns,
            "raw_payload_sha256": self.raw_payload_sha256,
            "source_id": self.source_id,
            "embodiment_id": self.embodiment_id,
            "environment_id": self.environment_id,
            "task_id": self.task_id,
            "step_index": self.step_index,
        })


@dataclass(frozen=True, slots=True)
class EmbodiedCaptureReceipt:
    event_id: str
    episode_id: str
    sequence: int
    family: str
    record_sha256: str
    raw_payload_sha256: str

    def __post_init__(self) -> None:
        for name, value in (("event_id", self.event_id), ("episode_id", self.episode_id), ("family", self.family)):
            _text(name, value)
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("capture sequence must be positive")
        for name, value in (("record_sha256", self.record_sha256), ("raw_payload_sha256", self.raw_payload_sha256)):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{name} must be lowercase SHA-256")


__all__ = [
    "ACTION_TRAIT",
    "EMBODIMENT_TRAIT",
    "EPISODE_TRAIT",
    "SENSOR_TRAIT",
    "ActionKind",
    "EmbodiedActionCommand",
    "EmbodiedCaptureReceipt",
    "EmbodiedEventProjection",
    "EmbodiedEventProjectionKind",
    "EmbodimentKind",
    "SensorModality",
    "action_spec_record",
    "action_spec_unit",
    "embodiment_actions",
    "embodiment_digest",
    "embodiment_id",
    "embodiment_record",
    "embodiment_sensors",
    "embodiment_unit",
    "episode_digest",
    "episode_embodiment_id",
    "episode_environment_id",
    "episode_id",
    "episode_record",
    "episode_task_id",
    "episode_unit",
    "require_action_spec",
    "require_embodiment",
    "require_episode",
    "require_sensor",
    "sensor_record",
    "sensor_unit",
]
