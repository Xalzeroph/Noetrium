from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from .action_codec_support import (
    MinecraftActionCodec,
    MinecraftActionContractError,
    error,
)
from .action_codecs_combat import CODECS as COMBAT_CODECS
from .action_codecs_interaction import CODECS as INTERACTION_CODECS
from .action_codecs_navigation import CODECS as NAVIGATION_CODECS
from .action_codecs_resources import CODECS as RESOURCE_CODECS
from .action_codecs_utility import CODECS as UTILITY_CODECS
from .contracts import MINECRAFT_ACTION_TYPES


_CODEC_GROUPS = (
    NAVIGATION_CODECS,
    RESOURCE_CODECS,
    COMBAT_CODECS,
    INTERACTION_CODECS,
    UTILITY_CODECS,
)


def _build_registry() -> dict[str, MinecraftActionCodec]:
    registry: dict[str, MinecraftActionCodec] = {}
    for group in _CODEC_GROUPS:
        for action_type, codec in group.items():
            if action_type in registry:
                raise RuntimeError(f"duplicate Minecraft action codec: {action_type}")
            registry[action_type] = codec
    if set(registry) != MINECRAFT_ACTION_TYPES:
        missing = sorted(MINECRAFT_ACTION_TYPES - set(registry))
        extra = sorted(set(registry) - MINECRAFT_ACTION_TYPES)
        raise RuntimeError(
            f"Minecraft action codec registry drift: missing={missing}, extra={extra}"
        )
    return registry


ACTION_CODECS: Mapping[str, MinecraftActionCodec] = MappingProxyType(_build_registry())


def validate_minecraft_action(
    action_type: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        codec = ACTION_CODECS[action_type]
    except KeyError as exc:
        raise error(action_type, "UNSUPPORTED_ACTION", "action type is not registered") from exc
    if not isinstance(payload, Mapping):
        raise error(action_type, "PAYLOAD_TYPE", "payload must be a mapping")
    return codec(payload)


__all__ = [
    "ACTION_CODECS",
    "MinecraftActionCodec",
    "MinecraftActionContractError",
    "validate_minecraft_action",
]
