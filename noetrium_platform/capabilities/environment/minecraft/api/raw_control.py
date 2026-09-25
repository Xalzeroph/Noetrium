from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)


@dataclass(frozen=True, slots=True)
class MinecraftRawControlObservation:
    """Low-level Minecraft observation for pixel/control agents."""

    frame_artifact_ref: str
    state: JsonObject = field(default_factory=dict)
    reward: float = 0.0
    success: bool = False
    terminated: bool = False
    truncated: bool = False
    receipt: JsonValue = None
    observation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.frame_artifact_ref) is not str or not self.frame_artifact_ref.strip():
            raise ValueError("Minecraft raw observation frame_artifact_ref is required")
        if not isinstance(self.state, Mapping):
            raise TypeError("Minecraft raw observation state must be an object")
        if isinstance(self.reward, bool) or not isinstance(self.reward, (int, float)):
            raise TypeError("Minecraft raw observation reward must be numeric")
        for name in ("success", "terminated", "truncated"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"Minecraft raw observation {name} must be boolean")
        object.__setattr__(self, "state", freeze_json(self.state))
        object.__setattr__(self, "reward", float(self.reward))
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "observation_digest",
            canonical_digest({
                "frame_artifact_ref": self.frame_artifact_ref,
                "state": thaw_json(self.state),
                "reward": self.reward,
                "success": self.success,
                "terminated": self.terminated,
                "truncated": self.truncated,
                "receipt": thaw_json(self.receipt),
            }),
        )

    @property
    def done(self) -> bool:
        return self.terminated or self.truncated

    def payload(self) -> JsonObject:
        return {
            "frame_artifact_ref": self.frame_artifact_ref,
            "state": thaw_json(self.state),
            "reward": self.reward,
            "success": self.success,
            "done": self.done,
            "terminated": self.terminated,
            "truncated": self.truncated,
            "receipt": thaw_json(self.receipt),
            "observation_digest": self.observation_digest,
        }


@dataclass(frozen=True, slots=True)
class MinecraftRawControlCommand:
    command_id: str
    sequence: int
    controls: JsonObject
    command_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.command_id) is not str or not self.command_id.strip():
            raise ValueError("Minecraft raw control command_id is required")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("Minecraft raw control sequence must be non-negative")
        if not isinstance(self.controls, Mapping):
            raise TypeError("Minecraft raw controls must be an object")
        object.__setattr__(self, "controls", freeze_json(self.controls))
        object.__setattr__(
            self,
            "command_digest",
            canonical_digest({
                "command_id": self.command_id,
                "sequence": self.sequence,
                "controls": thaw_json(self.controls),
            }),
        )


@runtime_checkable
class MinecraftRawControlBackendPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def reset(
        self,
        *,
        session_id: str,
        context: ExecutionContext,
    ) -> MinecraftRawControlObservation: ...

    def step(
        self,
        command: MinecraftRawControlCommand,
        *,
        context: ExecutionContext,
    ) -> MinecraftRawControlObservation: ...

    def close(self) -> None: ...


def validate_raw_control_backend(
    backend: MinecraftRawControlBackendPort,
) -> str:
    if not isinstance(backend, MinecraftRawControlBackendPort):
        raise TypeError(
            "Minecraft raw-control backend must satisfy MinecraftRawControlBackendPort"
        )
    return require_sha256(
        backend.identity_digest,
        "Minecraft raw-control backend identity_digest",
    )


__all__ = [
    "MinecraftRawControlBackendPort",
    "MinecraftRawControlCommand",
    "MinecraftRawControlObservation",
    "validate_raw_control_backend",
]
