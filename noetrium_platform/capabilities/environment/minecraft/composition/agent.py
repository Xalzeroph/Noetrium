from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Mapping

from noetrium_platform.capabilities.environment.runtime.api import ActionRequest, EnvironmentSession, Observation
from noetrium_platform.foundation.kernel.kernel import EffectCertainty
from noetrium_platform.capabilities.participant.agent.api import (
    AgentActionExecutorPort,
    AgentActionSequence,
    AgentDiagnosticsPort,
    AgentActionStep,
    AgentCompletionPort,
    AgentDiagnosticsPort,
    AgentEvidencePort,
    AgentGoal,
    AgentLoopCheckpoint,
    AgentLoopResult,
    AgentPlannerPort,
    AgentMemoryPort,
    AgentModeDecision,
    AgentModeDisposition,
    AgentObservation,
    AgentProgressPort,
    AgentSafetyDecision,
    AgentSafetyDisposition,
    AgentSkillCatalogPort,
    AgentSkillDescription,
    AgentSkillSelection,
    AgentStepReceipt,
    JsonValue,
)
from noetrium_platform.capabilities.participant.agent.runtime import AgentCognitionLoop
from noetrium_platform.capabilities.participant.agent.runtime.action_manager import AgentActionManager
from noetrium_platform.capabilities.participant.agent.runtime.memory import InMemoryAgentMemory
from noetrium_platform.capabilities.participant.agent.runtime.modes import ReactiveModeController
from noetrium_platform.capabilities.participant.agent.runtime.skill_library import InMemorySkillLibrary

from ..api import MINECRAFT_ACTION_TYPES, minecraft_action_catalog, validate_minecraft_action
from ..api.contracts import MinecraftActionCategory, MinecraftJsonValue
from ..runtime.planning import MinecraftBlueprintBlock, MinecraftBlueprintBuilder, MinecraftPlannedSequence


def _json_value(value: MinecraftJsonValue | tuple[MinecraftJsonValue, ...]) -> MinecraftJsonValue | list[MinecraftJsonValue]:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _json_mapping(value: Mapping[str, MinecraftJsonValue]) -> dict[str, JsonValue]:
    return {str(key): _json_value(item) for key, item in value.items()}


def _bounded_json(value: object, *, depth: int = 0) -> object:
    if depth >= 4:
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _bounded_json(item, depth=depth + 1)
            for key, item in list(value.items())[:64]
        }
    if isinstance(value, (list, tuple)):
        return [_bounded_json(item, depth=depth + 1) for item in value[:32]]
    return value


def _agent_effect_certainty(certainty: EffectCertainty | None) -> str:
    if certainty is EffectCertainty.EFFECT_CONFIRMED:
        return "confirmed"
    if certainty in {EffectCertainty.EFFECT_REJECTED, EffectCertainty.NO_EFFECT}:
        return "rejected"
    if certainty is EffectCertainty.EFFECT_POSSIBLE:
        return "possible"
    return "unknown"


def _grounded_action_receipt(receipt: AgentStepReceipt | None) -> bool:
    return bool(
        receipt
        and receipt.accepted
        and receipt.effect_certainty == "confirmed"
        and receipt.verified is not False
    )


def _agent_sequence(sequence: MinecraftPlannedSequence) -> AgentActionSequence:
    return AgentActionSequence(
        sequence.sequence_id,
        sequence.skill_id,
        tuple(
            AgentActionStep(
                action_id=f"{sequence.sequence_id}:{step.sequence_index}",
                action_type=step.action_type,
                payload=_json_mapping(step.payload),
                skill_id=sequence.skill_id,
                sequence_id=sequence.sequence_id,
                sequence_index=step.sequence_index,
                rationale=step.rationale,
                timeout_s=float(getattr(step, "timeout_s", 120.0)),
            )
            for step in sequence.steps
        ),
        completion_claim=sequence.completion_claim,
    )


class MinecraftAgentObservationPort:
    """Composition adapter from the MC EnvironmentSession to rich cognition state."""

    def __init__(self, session: EnvironmentSession) -> None:
        self._session = session
        self._sequence = 0

    def observe(self, context) -> AgentObservation:
        raw = self._session.observe(context)
        if not isinstance(raw.payload, Mapping) or not isinstance(raw.payload.get("state"), Mapping):
            raise ValueError("Minecraft observation payload must contain a mapping state")
        raw_state = raw.payload["state"]
        allowed_keys = (
            "health",
            "position",
            "inventory",
            "equipment",
            "nearby_entities",
            "hostile_entities",
            "nearby_blocks",
            "anchors",
            "mode",
            "time",
            "world_generation",
        )
        state = {
            key: _bounded_json(raw_state[key])
            for key in allowed_keys
            if key in raw_state
        }
        state.setdefault("world_generation", raw.generation)
        state.setdefault("nearby_entities", [])
        state.setdefault("hostile_entities", [])
        state.setdefault("inventory", {})
        state.setdefault("equipment", {})
        state.setdefault("nearby_blocks", [])
        state.setdefault("mode", "survival")
        self._sequence += 1
        return AgentObservation(
            f"agent:{raw.observation_id}:{self._sequence}", raw.generation, _json_mapping(state),
            modality="minecraft.rich_world", artifact_refs=raw.artifact_refs,
            evidence_payload=_json_mapping(dict(raw.payload)),
        )


class MinecraftAgentSkillCatalog(AgentSkillCatalogPort):
    _ALIASES = {
        "move": "goto", "navigate": "goto", "mine": "collect_block", "collect": "collect_block",
        "craft": "craft_item", "smelt": "smelt_item", "place": "place_block", "equip": "equip_item",
        "eat": "consume_item", "store": "chest_deposit", "retrieve": "chest_withdraw",
        "inspect_container": "chest_inspect", "attack": "attack_nearest", "defend": "defend_self",
        "explore_entities": "observe_entities", "farm": "till_and_sow", "sleep": "go_to_bed",
        "ride": "mount", "leave_vehicle": "dismount", "fish": "fish", "follow": "follow_player",
        "activate": "activate_nearest_block", "trade": "trade_villager", "use": "use_tool_on",
    }
    _HIGH_LEVEL = (
        AgentSkillDescription("minecraft.resource_plan", "planning", "Expand a validated resource plan into typed actions.", "{steps:[{action_type:string,payload:json_value,timeout_s?:number}]}", True),
        AgentSkillDescription("minecraft.build", "construction", "Place an ordered declarative blueprint.", "{blocks:[{item:string,position:{x:number,y:number,z:number},level?:integer}],observed_blocks?:object}", True),
        AgentSkillDescription("minecraft.explore", "exploration", "Refresh nearby entities and world affordances.", "{max_distance?:1..128,limit?:1..100}", False),
        AgentSkillDescription("minecraft.survive", "survival", "Use a bounded defensive response to immediate threats.", "{radius?:1..32,max_targets?:1..16,max_hits?:1..40}", True),
        AgentSkillDescription("minecraft.farm", "agriculture", "Till a safe soil block and sow one validated seed.", "{seed:string,max_distance?:1..32}", True),
        AgentSkillDescription("minecraft.social", "interaction", "Inspect or execute a bounded villager trade.", "{trade_index?:integer,max_trades?:1..16,max_distance?:1..32}", True),
        AgentSkillDescription("minecraft.transport", "movement", "Follow a player or mount/dismount a rideable entity.", "{player?:string,entity?:string,duration_s?:1..60}", True),
        AgentSkillDescription("minecraft.utility", "interaction", "Use doors, beds, controls, tools and bounded waiting.", "{target?:string,target_type?:block|entity,max_distance?:1..32}", True),
    )

    def describe(self) -> tuple[AgentSkillDescription, ...]:
        return tuple(
            AgentSkillDescription(
                f"minecraft.{contract.action_type}", contract.category, contract.description, contract.arguments,
                contract.mutates_world, safety_class="combat" if contract.category == MinecraftActionCategory.COMBAT.value else "ordinary",
            )
            for contract in minecraft_action_catalog()
        ) + self._HIGH_LEVEL

    def _action_type(self, skill_id: str, arguments: Mapping[str, JsonValue]) -> str:
        normalized = skill_id.removeprefix("minecraft.")
        action_type = self._ALIASES.get(normalized, normalized)
        if action_type not in MINECRAFT_ACTION_TYPES:
            raise ValueError(f"unknown Minecraft skill: {skill_id}")
        return action_type

    def expand(self, selection: AgentSkillSelection, *, observation: AgentObservation, context, sequence_id: str) -> AgentActionSequence:
        if selection.completion_claim:
            return AgentActionSequence(sequence_id, selection.skill_id, (), completion_claim=True)
        if selection.skill_id == "minecraft.build":
            raw_blocks = selection.arguments.get("blocks", [])
            observed = selection.arguments.get("observed_blocks", {})
            if not isinstance(raw_blocks, (list, tuple)) or not isinstance(observed, Mapping):
                raise ValueError("minecraft.build requires blocks list and observed_blocks mapping")
            blocks = tuple(
                MinecraftBlueprintBlock(dict(row["position"]), str(row["item"]), int(row.get("level", 0)))
                for row in raw_blocks
                if isinstance(row, Mapping) and isinstance(row.get("position"), Mapping) and str(row.get("item", "")).strip()
            )
            return _agent_sequence(MinecraftBlueprintBuilder().build(
                blocks,
                {str(key): str(value) for key, value in observed.items()},
                sequence_id=sequence_id,
                skill_id=selection.skill_id,
            ))
        if selection.skill_id == "minecraft.resource_plan":
            raw_steps = selection.arguments.get("steps", [])
            if not isinstance(raw_steps, (list, tuple)):
                raise ValueError("minecraft.resource_plan requires a steps list")
            steps: list[AgentActionStep] = []
            for index, row in enumerate(raw_steps):
                if not isinstance(row, Mapping) or not isinstance(row.get("payload"), Mapping):
                    raise ValueError("resource plan step shape is invalid")
                action_type = str(row.get("action_type", ""))
                payload = validate_minecraft_action(action_type, row["payload"])
                steps.append(AgentActionStep(
                    f"{sequence_id}:{index}",
                    action_type,
                    _json_mapping(payload),
                    selection.skill_id,
                    sequence_id,
                    index,
                    rationale=selection.rationale,
                    timeout_s=float(row.get("timeout_s", 120.0)),
                ))
            return AgentActionSequence(sequence_id, selection.skill_id, tuple(steps))
        if selection.skill_id == "minecraft.explore":
            selection = AgentSkillSelection("minecraft.observe_entities", selection.arguments, rationale=selection.rationale)
        elif selection.skill_id == "minecraft.survive":
            selection = AgentSkillSelection("minecraft.defend_self", selection.arguments, rationale=selection.rationale)
        elif selection.skill_id == "minecraft.farm":
            selection = AgentSkillSelection("minecraft.till_and_sow", selection.arguments, rationale=selection.rationale)
        elif selection.skill_id == "minecraft.social":
            selection = AgentSkillSelection("minecraft.trade_villager", selection.arguments, rationale=selection.rationale)
        elif selection.skill_id == "minecraft.transport":
            selection = AgentSkillSelection("minecraft.follow_player", selection.arguments, rationale=selection.rationale) if selection.arguments.get("player") else AgentSkillSelection("minecraft.mount", selection.arguments, rationale=selection.rationale)
        elif selection.skill_id == "minecraft.utility":
            target = str(selection.arguments.get("target", ""))
            selection = AgentSkillSelection("minecraft.use_tool_on", selection.arguments, rationale=selection.rationale) if target else AgentSkillSelection("minecraft.use_door", selection.arguments, rationale=selection.rationale)
        del observation, context
        action_type = self._action_type(selection.skill_id, selection.arguments)
        payload = validate_minecraft_action(action_type, selection.arguments)
        step = AgentActionStep(
            f"{sequence_id}:0", action_type, _json_mapping(payload), selection.skill_id, sequence_id, 0,
            interruptible=action_type not in {"craft_item", "smelt_item", "attack_entity"}, rationale=selection.rationale,
        )
        return AgentActionSequence(sequence_id, selection.skill_id, (step,))


class MinecraftAgentActionExecutor(AgentActionExecutorPort):
    def __init__(self, session: EnvironmentSession) -> None:
        self._session = session

    def execute(self, step: AgentActionStep, context) -> AgentStepReceipt:
        payload = validate_minecraft_action(step.action_type, step.payload)
        result = self._session.act(ActionRequest(step.action_id, step.action_type, payload, context))
        diagnostics = dict(result.diagnostics)
        if result.effect is not None:
            effect_payload = {
                "effect_id": result.effect.effect_id,
                "request_digest": result.effect.request_digest,
                "certainty": getattr(result.effect.certainty, "value", result.effect.certainty),
                "before_artifact": result.effect.before_artifact,
                "after_artifact": result.effect.after_artifact,
                "provider_receipt": result.effect.provider_receipt,
            }
            diagnostics.setdefault("effect_receipt", effect_payload)
            anchors = diagnostics.get("anchors")
            if not isinstance(anchors, (list, tuple)) or not anchors:
                anchors = [f"effect:{result.effect.effect_id}"]
                if result.effect.before_artifact:
                    anchors.append(f"before:{result.effect.before_artifact}")
                if result.effect.after_artifact:
                    anchors.append(f"after:{result.effect.after_artifact}")
                diagnostics["anchors"] = anchors
        verified_value = diagnostics.get("verified")
        verified = verified_value if isinstance(verified_value, bool) else None
        observation = None
        if result.observation is not None:
            if not isinstance(result.observation.payload, Mapping) or not isinstance(result.observation.payload.get("state"), Mapping):
                raise ValueError("Minecraft action result observation is missing state")
            observation = AgentObservation(
                f"agent:{result.observation.observation_id}", result.observation.generation,
                _json_mapping(dict(result.observation.payload["state"])), modality="minecraft.rich_world",
                artifact_refs=result.observation.artifact_refs,
                evidence_payload=_json_mapping(dict(result.observation.payload)),
            )
        certainty = _agent_effect_certainty(
            result.effect.certainty if result.effect is not None else None
        )
        effect_id = result.effect.effect_id if result.effect is not None else None
        return AgentStepReceipt(
            step.action_id, step.action_type, step.skill_id, step.sequence_id, bool(result.accepted), verified,
            observation=observation, effect_id=effect_id,
            effect_certainty=certainty, diagnostics=_json_mapping(diagnostics),
            payload=_json_mapping(payload),
        )


def _number(value: MinecraftJsonValue | None, default: float) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return default


class MinecraftAgentCompletion(AgentCompletionPort):
    def __init__(self) -> None:
        self._max_distance_by_goal: dict[str, float] = {}
        self._combat_receipts_by_goal: dict[str, set[str]] = {}
        self._placement_receipts_by_goal: dict[str, set[str]] = {}
        self._placed_items_by_goal: dict[str, dict[str, int]] = {}

    @staticmethod
    def _goal_key(goal: AgentGoal) -> str:
        return goal.digest

    def reset_goal(self, goal: AgentGoal) -> None:
        key = self._goal_key(goal)
        self._max_distance_by_goal.pop(key, None)
        self._combat_receipts_by_goal.pop(key, None)
        self._placement_receipts_by_goal.pop(key, None)
        self._placed_items_by_goal.pop(key, None)

    @staticmethod
    def _inventory_count(inventory: object, item: str) -> int:
        if not isinstance(inventory, Mapping):
            return 0
        needle = item.lower()
        total = 0
        for key, value in inventory.items():
            if needle not in str(key).lower():
                continue
            try:
                total += int(value)
            except (TypeError, ValueError):
                continue
        return total

    def is_complete(
        self,
        goal: AgentGoal,
        observation: AgentObservation,
        *,
        planner_finished: bool,
        last_receipt: AgentStepReceipt | None,
    ) -> bool:
        success = goal.context.get("success")
        if not isinstance(success, Mapping):
            return bool(observation.state.get("goal_complete", False)) or (
                planner_finished and _grounded_action_receipt(last_receipt)
            )
        kind = str(success.get("kind", "planner_finish"))
        if kind == "always":
            return True
        if kind == "planner_finish":
            return planner_finished and _grounded_action_receipt(last_receipt)
        if kind == "last_action_verified":
            return _grounded_action_receipt(last_receipt)
        if kind == "health_positive":
            return _number(observation.state.get("health"), 0) > 0
        if kind == "inventory_min":
            item, count = str(success.get("item", "")), int(success.get("count", 1))
            return self._inventory_count(observation.state.get("inventory"), item) >= count
        if kind == "inventory_delta_min":
            item, count = str(success.get("item", "")), int(success.get("count", 1))
            current = self._inventory_count(observation.state.get("inventory"), item)
            initial = self._inventory_count(success.get("initial_inventory"), item)
            return current - initial >= count
        if kind == "away_then_return":
            position = observation.state.get("position")
            anchors = observation.state.get("anchors")
            anchor_name = str(success.get("anchor", "spawn"))
            anchor = anchors.get(anchor_name) if isinstance(anchors, Mapping) else None
            if not isinstance(position, Mapping) or not isinstance(anchor, Mapping):
                return False
            distance = sum(
                (float(position.get(axis, 0)) - float(anchor.get(axis, 0))) ** 2
                for axis in ("x", "y", "z")
            ) ** 0.5
            previous = self._max_distance_by_goal.get(self._goal_key(goal), 0.0)
            self._max_distance_by_goal[self._goal_key(goal)] = max(previous, distance)
            return (
                self._max_distance_by_goal[self._goal_key(goal)]
                >= float(success.get("min_departure_distance", 16))
                and distance <= float(success.get("return_radius", 5))
            )
        if kind == "combat_survived":
            receipt_id = last_receipt.action_id if last_receipt is not None else ""
            combat_types = {
                "defend_self", "attack_nearest", "attack_entity", "ranged_attack"
            }
            seen = self._combat_receipts_by_goal.setdefault(self._goal_key(goal), set())
            if (
                last_receipt is not None
                and receipt_id not in seen
                and last_receipt.action_type in combat_types
                and _grounded_action_receipt(last_receipt)
            ):
                seen.add(receipt_id)
            return (
                _number(observation.state.get("health"), 0) > 0
                and len(seen) >= int(success.get("min_verified_combat_actions", 1))
            )
        if kind == "blueprint_complete":
            required = success.get("blocks", ())
            if not isinstance(required, (list, tuple)):
                return False
            required_items: dict[str, int] = {}
            for row in required:
                item = row.get("item") if isinstance(row, Mapping) else row
                item_name = str(item or "").strip().lower()
                if item_name:
                    required_items[item_name] = required_items.get(item_name, 0) + 1
            if not required_items:
                return False
            receipt_id = last_receipt.action_id if last_receipt is not None else ""
            key = self._goal_key(goal)
            seen = self._placement_receipts_by_goal.setdefault(key, set())
            if (
                last_receipt is not None
                and receipt_id not in seen
                and last_receipt.action_type == "place_block"
                and _grounded_action_receipt(last_receipt)
            ):
                item = last_receipt.payload.get("item") or last_receipt.payload.get("block")
                item_name = str(item or "").strip().lower()
                if item_name in required_items:
                    seen.add(receipt_id)
                    placed = self._placed_items_by_goal.setdefault(key, {})
                    placed[item_name] = placed.get(item_name, 0) + 1
            placed = self._placed_items_by_goal.get(key, {})
            return all(placed.get(item, 0) >= count for item, count in required_items.items())
        if kind == "observed_entity":
            entities = observation.state.get("nearby_entities")
            query = str(success.get("entity", "")).lower()
            return isinstance(entities, (list, tuple)) and any(
                query in str(row).lower() for row in entities
            )
        if kind == "near_position":
            position, target = observation.state.get("position"), success.get("position")
            if not isinstance(position, Mapping) or not isinstance(target, Mapping):
                return False
            radius = float(success.get("radius", 2))
            return sum(
                (float(position.get(axis, 0)) - float(target.get(axis, 0))) ** 2
                for axis in ("x", "y", "z")
            ) <= radius ** 2
        if kind == "near_anchor":
            position, anchors = observation.state.get("position"), observation.state.get("anchors")
            anchor = anchors.get(str(success.get("anchor", ""))) if isinstance(anchors, Mapping) else None
            if not isinstance(position, Mapping) or not isinstance(anchor, Mapping):
                return False
            radius = float(success.get("radius", 3))
            return sum(
                (float(position.get(axis, 0)) - float(anchor.get(axis, 0))) ** 2
                for axis in ("x", "y", "z")
            ) <= radius ** 2
        raise ValueError(f"unknown Minecraft completion kind: {kind}")


class MinecraftAgentSafetySupervisor:
    def review(self, goal: AgentGoal, observation: AgentObservation, selection: AgentSkillSelection, sequence: AgentActionSequence, context) -> AgentSafetyDecision:
        del goal, sequence, context
        if _number(observation.state.get("health"), 20) <= 0:
            return AgentSafetyDecision(AgentSafetyDisposition.ABORT, "player health is zero", "minecraft.health")
        if selection.skill_id.endswith("attack_player"):
            return AgentSafetyDecision(AgentSafetyDisposition.ABORT, "player-directed combat is disabled", "minecraft.combat_policy")
        return AgentSafetyDecision(AgentSafetyDisposition.ALLOW, "no safety intervention", "minecraft.safety")


class MinecraftReactiveModeController(ReactiveModeController):
    def __init__(self, catalog: MinecraftAgentSkillCatalog | None = None) -> None:
        super().__init__()
        self._catalog = catalog or MinecraftAgentSkillCatalog()

    def review(self, goal: AgentGoal, observation: AgentObservation, selection: AgentSkillSelection, sequence: AgentActionSequence, context) -> AgentModeDecision | None:
        del goal, sequence
        if _number(observation.state.get("health"), 20) <= 0:
            return AgentModeDecision("self_preservation.dead", AgentModeDisposition.ABORT, "no action is safe after death")
        hostiles = observation.state.get("hostile_entities", ())
        if isinstance(hostiles, (list, tuple)) and hostiles and not selection.skill_id.endswith(("defend_self", "attack_nearest", "attack_entity", "ranged_attack")):
            replacement = self._catalog.expand(
                AgentSkillSelection("minecraft.defend_self", {"radius": 12, "max_targets": 4}, rationale="reactive self-defense"),
                observation=observation, context=context, sequence_id=f"mode:defend:{observation.observation_id}",
            )
            return AgentModeDecision("self_defense", AgentModeDisposition.PREEMPT, "hostile entities are present", replacement)
        return None


@dataclass(frozen=True, slots=True)
class MinecraftAgentPortBundle:
    observation: MinecraftAgentObservationPort
    skills: MinecraftAgentSkillCatalog
    executor: MinecraftAgentActionExecutor
    memory: AgentMemoryPort
    skill_library: InMemorySkillLibrary
    safety: MinecraftAgentSafetySupervisor
    completion: MinecraftAgentCompletion
    reactive_modes: MinecraftReactiveModeController


def compose_minecraft_agent_ports(
    session: EnvironmentSession,
    *,
    memory: AgentMemoryPort | None = None,
) -> MinecraftAgentPortBundle:
    skills = MinecraftAgentSkillCatalog()
    return MinecraftAgentPortBundle(
        MinecraftAgentObservationPort(session), skills, MinecraftAgentActionExecutor(session), memory or InMemoryAgentMemory(),
        InMemorySkillLibrary(), MinecraftAgentSafetySupervisor(), MinecraftAgentCompletion(), MinecraftReactiveModeController(skills),
    )


class MinecraftCognitionRunner:
    def __init__(self, session: EnvironmentSession, *, planner: AgentPlannerPort, evidence: AgentEvidencePort, progress: AgentProgressPort, memory: AgentMemoryPort | None = None, diagnostics: AgentDiagnosticsPort | None = None, clock: Callable[[], float] | None = None) -> None:
        if planner is None or evidence is None or progress is None:
            raise ValueError("Minecraft cognition runner requires planner, evidence and progress ports")
        loop_clock = clock or time.monotonic
        bundle = compose_minecraft_agent_ports(session, memory=memory)
        self._bundle = bundle
        self._loop = AgentCognitionLoop(
            observation=bundle.observation, planner=planner, skills=bundle.skills,
            executor=AgentActionManager(bundle.executor, clock=loop_clock), memory=bundle.memory,
            safety=bundle.safety, completion=bundle.completion, evidence=evidence, progress=progress,
            skill_library=bundle.skill_library, reactive_modes=bundle.reactive_modes, diagnostics=diagnostics, clock=loop_clock,
        )

    @property
    def ports(self) -> MinecraftAgentPortBundle:
        return self._bundle

    def run(self, goal: AgentGoal, context, *, session_id: str | None = None, checkpoint: AgentLoopCheckpoint | None = None) -> AgentLoopResult:
        return self._loop.run(goal, context, session_id=session_id, checkpoint=checkpoint)


class MinecraftCognitionFactory:
    """Bind the generic cognition loop to a concrete MC environment session."""

    def create(
        self,
        *,
        session: EnvironmentSession,
        planner: AgentPlannerPort,
        evidence: AgentEvidencePort,
        progress: AgentProgressPort,
        memory: AgentMemoryPort | None = None,
        diagnostics: AgentDiagnosticsPort | None,
    ) -> MinecraftCognitionRunner:
        return MinecraftCognitionRunner(
            session,
            planner=planner,
            evidence=evidence,
            progress=progress,
            memory=memory,
            diagnostics=diagnostics,
        )


__all__ = [
    "MinecraftAgentActionExecutor", "MinecraftAgentCompletion", "MinecraftAgentObservationPort",
    "MinecraftAgentPortBundle", "MinecraftAgentSafetySupervisor", "MinecraftAgentSkillCatalog",
    "MinecraftCognitionFactory", "MinecraftCognitionRunner", "MinecraftReactiveModeController", "compose_minecraft_agent_ports",
]
