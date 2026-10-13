from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.substrate.api import MultimodalPart
from noetrium_platform.foundation.kernel.kernel import (
    JsonInput,
    JsonValue,
    canonical_digest,
    freeze_json,
)


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    result=float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


class WorldModelMode(StrEnum):
    FORWARD_DYNAMICS = "forward_dynamics"
    POLICY = "policy"
    INVERSE_DYNAMICS = "inverse_dynamics"


@dataclass(frozen=True, slots=True)
class WorldModelActionStep:
    """One action at one logical time in an open embodiment-specific schema."""

    step_index: int
    payload: JsonValue
    timestamp_ns: int | None = None
    duration_ns: int | None = None

    def __post_init__(self) -> None:
        if type(self.step_index) is not int or self.step_index < 0:
            raise ValueError("world-model action step_index must be non-negative")
        object.__setattr__(self, "payload", freeze_json(self.payload))
        for name in ("timestamp_ns","duration_ns"):
            value=getattr(self,name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"world-model action {name} must be non-negative")


@dataclass(frozen=True, slots=True)
class WorldModelActionTrajectory:
    action_schema_id: str
    steps: tuple[WorldModelActionStep, ...]
    action_rate_hz: float | None = None
    embodiment_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.action_schema_id,"world-model action_schema_id")
        if not isinstance(self.steps,tuple) or not self.steps:
            raise TypeError("world-model action trajectory requires non-empty steps")
        if any(not isinstance(step,WorldModelActionStep) for step in self.steps):
            raise TypeError("world-model action trajectory steps must be typed")
        indices=tuple(step.step_index for step in self.steps)
        if indices != tuple(range(len(indices))):
            raise ValueError(
                "world-model action trajectory step indices must be contiguous from zero"
            )
        if self.action_rate_hz is not None:
            value=_finite(self.action_rate_hz,"world-model action_rate_hz")
            if value <= 0:
                raise ValueError("world-model action_rate_hz must be positive")
            object.__setattr__(self,"action_rate_hz",value)
        if self.embodiment_id is not None:
            _text(self.embodiment_id,"world-model embodiment_id")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class WorldModelInput:
    """Provider-neutral action-conditioned world-model invocation."""

    mode: WorldModelMode
    observations: tuple[MultimodalPart, ...]
    task_prompt: str | None = None
    action_trajectory: WorldModelActionTrajectory | None = None
    state: JsonValue | None = None
    rollout_horizon: int | None = None
    candidates: int = 1
    parameters: Mapping[str, JsonInput] = field(default_factory=dict)
    schema_id: str = field(init=False, default="model.world-model.input.v1")

    def __post_init__(self) -> None:
        if not isinstance(self.mode,WorldModelMode):
            raise TypeError("world-model mode must be WorldModelMode")
        if not isinstance(self.observations,tuple) or not self.observations:
            raise TypeError("world-model input requires observations")
        if any(not isinstance(part,MultimodalPart) for part in self.observations):
            raise TypeError("world-model observations must be MultimodalPart values")
        if self.task_prompt is not None:
            _text(self.task_prompt,"world-model task_prompt")
        if (
            self.action_trajectory is not None
            and not isinstance(self.action_trajectory,WorldModelActionTrajectory)
        ):
            raise TypeError("world-model action_trajectory must be typed")
        if self.state is not None:
            object.__setattr__(self,"state",freeze_json(self.state))
        if self.rollout_horizon is not None and (
            type(self.rollout_horizon) is not int or self.rollout_horizon <= 0
        ):
            raise ValueError("world-model rollout_horizon must be positive")
        if type(self.candidates) is not int or self.candidates <= 0:
            raise ValueError("world-model candidates must be positive")
        if not isinstance(self.parameters,Mapping):
            raise TypeError("world-model parameters must be a mapping")
        object.__setattr__(self,"parameters",freeze_json(self.parameters))

        if (
            self.mode is WorldModelMode.FORWARD_DYNAMICS
            and self.action_trajectory is None
        ):
            raise ValueError(
                "forward_dynamics world model requires an action trajectory"
            )
        if (
            self.mode is WorldModelMode.POLICY
            and self.task_prompt is None
            and self.state is None
        ):
            raise ValueError(
                "policy world model requires task_prompt or state conditioning"
            )
        if (
            self.mode is WorldModelMode.INVERSE_DYNAMICS
            and self.action_trajectory is not None
        ):
            raise ValueError(
                "inverse_dynamics world model predicts actions and cannot receive them"
            )

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class WorldModelRollout:
    """One predicted world trajectory with optional predicted actions/state."""

    media: tuple[MultimodalPart, ...]
    predicted_actions: WorldModelActionTrajectory | None = None
    predicted_state: JsonValue | None = None
    score: float | None = None
    terminated: bool | None = None
    metadata: Mapping[str, JsonInput] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.media,tuple):
            raise TypeError("world-model rollout media must be a tuple")
        if any(not isinstance(part,MultimodalPart) for part in self.media):
            raise TypeError("world-model rollout media must be MultimodalPart values")
        if (
            self.predicted_actions is not None
            and not isinstance(self.predicted_actions,WorldModelActionTrajectory)
        ):
            raise TypeError("world-model predicted_actions must be typed")
        if self.predicted_state is not None:
            object.__setattr__(
                self,"predicted_state",freeze_json(self.predicted_state)
            )
        if self.score is not None:
            object.__setattr__(
                self,"score",_finite(self.score,"world-model rollout score")
            )
        if self.terminated is not None and type(self.terminated) is not bool:
            raise TypeError("world-model rollout terminated must be bool or None")
        if not isinstance(self.metadata,Mapping):
            raise TypeError("world-model rollout metadata must be a mapping")
        object.__setattr__(self,"metadata",freeze_json(self.metadata))
        if not self.media and self.predicted_actions is None and self.predicted_state is None:
            raise ValueError(
                "world-model rollout requires predicted media, actions, or state"
            )


@dataclass(frozen=True, slots=True)
class WorldModelOutput:
    mode: WorldModelMode
    model_revision: str
    rollouts: tuple[WorldModelRollout, ...]
    primary_index: int = 0
    metadata: Mapping[str, JsonInput] = field(default_factory=dict)
    schema_id: str = field(init=False, default="model.world-model.output.v1")

    def __post_init__(self) -> None:
        if not isinstance(self.mode,WorldModelMode):
            raise TypeError("world-model output mode must be typed")
        _text(self.model_revision,"world-model output model_revision")
        if not isinstance(self.rollouts,tuple) or not self.rollouts:
            raise TypeError("world-model output requires rollouts")
        if any(not isinstance(row,WorldModelRollout) for row in self.rollouts):
            raise TypeError("world-model rollouts must be typed")
        if (
            type(self.primary_index) is not int
            or not 0 <= self.primary_index < len(self.rollouts)
        ):
            raise ValueError("world-model primary_index is out of range")
        if not isinstance(self.metadata,Mapping):
            raise TypeError("world-model output metadata must be a mapping")
        object.__setattr__(self,"metadata",freeze_json(self.metadata))

    @property
    def primary(self) -> WorldModelRollout:
        return self.rollouts[self.primary_index]

    def digest(self) -> str:
        return canonical_digest(self)


__all__ = [
    "WorldModelActionStep",
    "WorldModelActionTrajectory",
    "WorldModelInput",
    "WorldModelMode",
    "WorldModelOutput",
    "WorldModelRollout",
]
