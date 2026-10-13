from __future__ import annotations

from .action_codecs import MinecraftActionContractError, validate_minecraft_action
from .contracts import MINECRAFT_ACTION_SPECS, MINECRAFT_ACTION_SPEC_BY_TYPE, MinecraftPlannerActionContract, minecraft_action_planner_contract, minecraft_action_timeout_multiplier


def minecraft_action_timeout(action_type: str, base_timeout_s: float) -> float:
    """Return the catalog-bound timeout without granting callers arbitrary duration."""
    if base_timeout_s <= 0:
        raise ValueError("Minecraft base action timeout must be positive")
    try:
        spec = MINECRAFT_ACTION_SPEC_BY_TYPE[action_type]
    except KeyError as exc:
        raise MinecraftActionContractError(action_type, "UNSUPPORTED_ACTION", "action type is not registered") from exc
    return base_timeout_s * minecraft_action_timeout_multiplier(spec)


_MINECRAFT_PLANNER_ACTION_CATALOG = tuple(
    minecraft_action_planner_contract(spec) for spec in MINECRAFT_ACTION_SPECS
)


def minecraft_action_catalog() -> tuple[MinecraftPlannerActionContract, ...]:
    """Return the immutable planner view compiled from the Unit catalog once."""
    return _MINECRAFT_PLANNER_ACTION_CATALOG


__all__ = ["MinecraftActionContractError", "minecraft_action_catalog", "minecraft_action_timeout", "validate_minecraft_action"]
