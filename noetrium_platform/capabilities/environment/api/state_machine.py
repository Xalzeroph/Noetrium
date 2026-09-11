from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Protocol, TypeAlias

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_digest

from .contracts import ActionRequest


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]
JsonInput: TypeAlias = (
    JsonScalar | list["JsonInput"] | tuple["JsonInput", ...] | Mapping[str, "JsonInput"]
)
JsonMutableValue: TypeAlias = JsonScalar | list["JsonMutableValue"] | dict[str, "JsonMutableValue"]


def _freeze_json(value: JsonInput, *, path: str) -> JsonValue:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"state-machine JSON contains a non-finite number at {path}")
        return value
    if isinstance(value, Mapping):
        rows: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"state-machine JSON key is not a string at {path}")
            rows[key] = _freeze_json(item, path=f"{path}.{key}")
        return MappingProxyType(rows)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    raise TypeError(
        f"state-machine JSON contains unsupported {type(value).__name__} at {path}"
    )


def freeze_json_mapping(
    value: Mapping[str, JsonInput],
    *,
    field: str,
) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    frozen = _freeze_json(value, path=field)
    assert isinstance(frozen, Mapping)
    return frozen


def thaw_json(value: JsonValue) -> JsonMutableValue:
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def thaw_json_mapping(value: Mapping[str, JsonValue]) -> dict[str, JsonMutableValue]:
    return {key: thaw_json(item) for key, item in value.items()}


@dataclass(frozen=True, slots=True)
class StateMachineDynamicsIdentity:
    dynamics_id: str
    implementation_version: str
    artifact_digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.dynamics_id, str)
            or not self.dynamics_id.strip()
            or not isinstance(self.implementation_version, str)
            or not self.implementation_version.strip()
        ):
            raise ValueError("state-machine dynamics identity is incomplete")
        if (
            not isinstance(self.artifact_digest, str)
            or self.artifact_digest != self.artifact_digest.lower()
            or len(self.artifact_digest) != 64
            or any(
                char not in "0123456789abcdef" for char in self.artifact_digest
            )
        ):
            raise ValueError("state-machine dynamics artifact_digest must be SHA-256")


@dataclass(frozen=True, slots=True)
class StateMachineEnvironmentSpec:
    """Immutable scientific configuration for one deterministic closed world."""

    environment_id: str
    dynamics: StateMachineDynamicsIdentity
    initial_state: Mapping[str, JsonValue]
    action_types: tuple[str, ...]
    implementation_version: str = "1"
    abi_version: str = "1"
    schema_version: str = "1"

    def __post_init__(self) -> None:
        required = (
            self.environment_id,
            self.implementation_version,
            self.abi_version,
            self.schema_version,
        )
        if any(not isinstance(value, str) or not value.strip() for value in required):
            raise ValueError("state-machine environment identity is incomplete")
        if not self.action_types or any(
            not isinstance(item, str) or not item.strip() for item in self.action_types
        ):
            raise ValueError("state-machine action types must be non-empty")
        if len(self.action_types) != len(set(self.action_types)):
            raise ValueError("state-machine action types must be unique")
        object.__setattr__(
            self,
            "initial_state",
            freeze_json_mapping(self.initial_state, field="initial_state"),
        )

    def scientific_identity_digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class StateTransition:
    """Pure transition output; the runtime owns mutation and action identity."""

    state: Mapping[str, JsonValue]
    accepted: bool
    diagnostics: Mapping[str, JsonValue]
    artifact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise TypeError("state-machine transition accepted must be boolean")
        if any(
            not isinstance(ref, str) or not ref.strip() for ref in self.artifact_refs
        ):
            raise ValueError("state-machine transition artifact refs must be non-empty")
        if len(self.artifact_refs) != len(set(self.artifact_refs)):
            raise ValueError("state-machine transition artifact refs must be unique")
        object.__setattr__(self, "state", freeze_json_mapping(self.state, field="state"))
        object.__setattr__(
            self,
            "diagnostics",
            freeze_json_mapping(self.diagnostics, field="diagnostics"),
        )


class StateMachineDynamicsPort(Protocol):
    """Domain semantics injected behind the generic closed-world runtime."""

    @property
    def identity(self) -> StateMachineDynamicsIdentity: ...

    def transition(
        self,
        state: Mapping[str, JsonValue],
        request: ActionRequest,
        context: ExecutionContext,
    ) -> StateTransition: ...


__all__ = [
    "JsonScalar",
    "JsonInput",
    "JsonMutableValue",
    "JsonValue",
    "StateMachineDynamicsIdentity",
    "StateMachineDynamicsPort",
    "StateMachineEnvironmentSpec",
    "StateTransition",
    "freeze_json_mapping",
    "thaw_json",
    "thaw_json_mapping",
]
