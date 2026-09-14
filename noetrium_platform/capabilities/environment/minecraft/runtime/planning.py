from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from ..api import validate_minecraft_action
from ..api.contracts import MinecraftJsonValue


@dataclass(frozen=True, slots=True)
class MinecraftRecipe:
    item: str
    count: int
    ingredients: Mapping[str, int]
    process: str = "craft"

    def __post_init__(self) -> None:
        if not self.item.strip() or self.count < 1 or self.process not in {"craft", "smelt"}:
            raise ValueError("Minecraft recipe is invalid")
        if any(not str(name).strip() or int(value) < 1 for name, value in self.ingredients.items()):
            raise ValueError("Minecraft recipe ingredients are invalid")


@dataclass(frozen=True, slots=True)
class MinecraftPlannedStep:
    """Environment-owned typed action data; Agent ABI conversion stays in composition."""

    action_type: str
    payload: Mapping[str, MinecraftJsonValue]
    sequence_index: int
    rationale: str = ""
    timeout_s: float = 120.0

    def __post_init__(self) -> None:
        if (
            not self.action_type.strip()
            or self.sequence_index < 0
            or not isinstance(self.payload, Mapping)
            or isinstance(self.timeout_s, bool)
            or not isinstance(self.timeout_s, (int, float))
            or not math.isfinite(float(self.timeout_s))
            or self.timeout_s <= 0
        ):
            raise ValueError("Minecraft planned step is invalid")


@dataclass(frozen=True, slots=True)
class MinecraftPlannedSequence:
    sequence_id: str
    skill_id: str
    steps: tuple[MinecraftPlannedStep, ...]
    completion_claim: bool = False

    def __post_init__(self) -> None:
        if not self.sequence_id.strip() or not self.skill_id.strip():
            raise ValueError("Minecraft planned sequence identity is required")
        if not self.completion_claim and not self.steps:
            raise ValueError("Minecraft planned sequence cannot be empty")


@dataclass(frozen=True, slots=True)
class MinecraftResourcePlan:
    target: str
    count: int
    steps: tuple[tuple[str, Mapping[str, MinecraftJsonValue]], ...]
    missing: tuple[str, ...] = ()
    digest: str = ""

    def __post_init__(self) -> None:
        if not self.target.strip() or self.count < 1:
            raise ValueError("resource plan target/count are invalid")
        computed = canonical_digest({"target": self.target, "count": self.count, "steps": self.steps, "missing": self.missing})
        if self.digest and self.digest != computed:
            raise ValueError("resource plan digest mismatch")
        if not self.digest:
            object.__setattr__(self, "digest", computed)

    def to_action_sequence(self, *, sequence_id: str, skill_id: str = "minecraft.resource_plan") -> MinecraftPlannedSequence:
        return MinecraftPlannedSequence(
            sequence_id,
            skill_id,
            tuple(
                MinecraftPlannedStep(action_type, dict(payload), index, "resource dependency plan")
                for index, (action_type, payload) in enumerate(self.steps)
            ),
        )


class MinecraftResourcePlanner:
    """Deterministic recipe/dependency expansion with cycle detection."""

    def __init__(self, recipes: Mapping[str, MinecraftRecipe]) -> None:
        self._recipes = dict(recipes)

    def plan(self, target: str, count: int, inventory: Mapping[str, int], *, max_depth: int = 32) -> MinecraftResourcePlan:
        if not target.strip() or count < 1 or max_depth < 1:
            raise ValueError("resource planning request is invalid")
        available = {str(name): int(value) for name, value in inventory.items()}
        steps: list[tuple[str, Mapping[str, MinecraftJsonValue]]] = []
        missing: list[str] = []
        visiting: set[str] = set()

        def ensure(item: str, required: int, depth: int) -> None:
            if required <= 0:
                return
            if depth > max_depth:
                missing.append(item)
                return
            current = available.get(item, 0)
            if current >= required:
                available[item] = current - required
                return
            deficit = required - current
            available[item] = 0
            recipe = self._recipes.get(item)
            if recipe is None:
                missing.append(item)
                steps.append(("collect_block", validate_minecraft_action("collect_block", {"block": item, "count": deficit})))
                available[item] = deficit
                return
            if item in visiting:
                raise ValueError(f"circular Minecraft recipe dependency: {item}")
            visiting.add(item)
            batches = (deficit + recipe.count - 1) // recipe.count
            for ingredient, ingredient_count in recipe.ingredients.items():
                ensure(ingredient, ingredient_count * batches, depth + 1)
            action_type = "craft_item" if recipe.process == "craft" else "smelt_item"
            payload: dict[str, MinecraftJsonValue] = {"item": item, "count": batches * recipe.count}
            if action_type == "smelt_item":
                payload["max_wait_s"] = 90
            steps.append((action_type, validate_minecraft_action(action_type, payload)))
            available[item] = available.get(item, 0) + batches * recipe.count
            available[item] -= required
            visiting.remove(item)

        ensure(target, count, 0)
        return MinecraftResourcePlan(target, count, tuple(steps), tuple(dict.fromkeys(missing)))


@dataclass(frozen=True, slots=True)
class MinecraftBlueprintBlock:
    position: Mapping[str, float]
    item: str
    level: int = 0

    def __post_init__(self) -> None:
        if not self.item.strip() or self.level < 0 or set(self.position) != {"x", "y", "z"}:
            raise ValueError("blueprint block is invalid")


class MinecraftBlueprintBuilder:
    """Turns a declarative blueprint diff into verified typed place actions."""

    def build(self, blueprint: tuple[MinecraftBlueprintBlock, ...], observed_blocks: Mapping[str, str], *, sequence_id: str, skill_id: str = "minecraft.build") -> MinecraftPlannedSequence:
        ordered = sorted(blueprint, key=lambda block: (block.level, block.position["y"], block.position["x"], block.position["z"], block.item))
        steps: list[MinecraftPlannedStep] = []
        for block in ordered:
            key = self._position_key(block.position)
            if observed_blocks.get(key) == block.item:
                continue
            payload = validate_minecraft_action("place_block", {"item": block.item, "position": dict(block.position)})
            steps.append(MinecraftPlannedStep(
                action_type="place_block", payload=payload, sequence_index=len(steps),
                rationale=f"blueprint level {block.level}",
            ))
        return MinecraftPlannedSequence(sequence_id, skill_id, tuple(steps), completion_claim=not steps)

    @staticmethod
    def _position_key(position: Mapping[str, float]) -> str:
        return ",".join(str(int(float(position[axis]))) for axis in ("x", "y", "z"))


__all__ = [
    "MinecraftBlueprintBlock",
    "MinecraftBlueprintBuilder",
    "MinecraftPlannedSequence",
    "MinecraftPlannedStep",
    "MinecraftRecipe",
    "MinecraftResourcePlan",
    "MinecraftResourcePlanner",
]
