from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, canonical_bytes, canonical_digest, freeze_json
from noetrium_platform.research.execution.machines import (
    ContextBlockProgram,
    ContextBudgetExceeded,
    ContextProgram,
    ContextRendererRegistry,
    ContextRenderRequest,
    ContextRenderResult,
    compile_context,
)

from ..api.cognition import AgentGoal, AgentMemoryContext, AgentObservation, AgentSkillDescription
from .model_view import (
    AGENT_ACTION_HISTORY_VIEW_SCHEMA,
    AgentActionHistoryProjectionReceipt,
    project_action_history,
)


@dataclass(frozen=True, slots=True)
class CompiledAgentContext:
    schema_version: str
    context_program_digest: str
    context_binding_digest: str
    text: str
    block_ids: tuple[str, ...]
    omitted_block_ids: tuple[str, ...]
    compacted_block_ids: tuple[str, ...]
    history_projection: AgentActionHistoryProjectionReceipt | None = None

    @property
    def lossy(self) -> bool:
        return bool(self.omitted_block_ids or self.compacted_block_ids)


class AgentContextBudgetExceeded(ContextBudgetExceeded):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        json.loads(canonical_bytes(value)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def default_agent_context_program(*, max_chars: int = 12_000) -> ContextProgram:
    return ContextProgram(
        program_id="agent.default-context",
        version="3",
        max_chars=max_chars,
        blocks=(
            ContextBlockProgram(
                "system",
                "agent.context.system",
                priority=100,
                required=True,
                configuration={
                    "text": (
                        "Choose one typed skill and never claim completion "
                        "without state evidence."
                    )
                },
            ),
            ContextBlockProgram(
                "goal",
                "agent.context.goal",
                priority=90,
                required=True,
            ),
            ContextBlockProgram(
                "observation",
                "agent.context.observation",
                priority=80,
                required=True,
            ),
            ContextBlockProgram(
                "skills",
                "agent.context.skills",
                priority=70,
                required=True,
            ),
            ContextBlockProgram(
                "memory",
                "agent.context.memory",
                priority=50,
            ),
            ContextBlockProgram(
                "prior_actions",
                "agent.context.action-history",
                priority=40,
            ),
        ),
    )


def _history_receipt_payload(receipt: AgentActionHistoryProjectionReceipt) -> JsonObject:
    return {
        "schema_version": receipt.schema_version,
        "source_count": receipt.source_count,
        "included_count": receipt.included_count,
        "omitted_count": receipt.omitted_count,
        "first_included_index": receipt.first_included_index,
        "source_digest": receipt.source_digest,
        "included_digest": receipt.included_digest,
        "omitted_digest": receipt.omitted_digest,
    }


def _history_receipt_from_payload(value: object) -> AgentActionHistoryProjectionReceipt | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("agent history projection receipt must be an object")
    return AgentActionHistoryProjectionReceipt(
        schema_version=str(value["schema_version"]),
        source_count=int(value["source_count"]),
        included_count=int(value["included_count"]),
        omitted_count=int(value["omitted_count"]),
        first_included_index=(
            None
            if value.get("first_included_index") is None
            else int(value["first_included_index"])
        ),
        source_digest=str(value["source_digest"]),
        included_digest=str(value["included_digest"]),
        omitted_digest=str(value["omitted_digest"]),
    )


def _context_renderer_implementation_digest(renderer: str) -> str:
    return canonical_digest({
        "surface": "agent-context-renderer",
        "renderer": renderer,
        "implementation_revision": 1,
    })


def default_agent_context_renderers() -> ContextRendererRegistry:
    registry = ContextRendererRegistry()

    def system(request: ContextRenderRequest) -> ContextRenderResult:
        text = request.block.configuration.get("text")
        if type(text) is not str or not text.strip():
            raise ValueError("agent system context block requires configured text")
        return ContextRenderResult(text.strip())

    def goal(request: ContextRenderRequest) -> ContextRenderResult:
        value = request.inputs.get("goal")
        if not isinstance(value, Mapping):
            raise TypeError("agent context goal input must be an object")
        return ContextRenderResult(_canonical_json(value))

    def observation(request: ContextRenderRequest) -> ContextRenderResult:
        value = request.inputs.get("observation")
        if not isinstance(value, Mapping):
            raise TypeError("agent context observation input must be an object")
        state = value.get("state")
        if not isinstance(state, Mapping):
            raise TypeError("agent context observation state must be an object")
        return ContextRenderResult(_canonical_json(state))

    def skills(request: ContextRenderRequest) -> ContextRenderResult:
        value = request.inputs.get("skills", ())
        if not isinstance(value, (tuple, list)):
            raise TypeError("agent context skills input must be a sequence")
        return ContextRenderResult(_canonical_json(value))

    def memory(request: ContextRenderRequest) -> ContextRenderResult:
        value = request.inputs.get("memory")
        if not isinstance(value, Mapping):
            raise TypeError("agent context memory input must be an object")
        text = value.get("context_text", "")
        if type(text) is not str:
            raise TypeError("agent context memory text must be text")
        return ContextRenderResult(text or "(no verified memory)")

    def action_history(request: ContextRenderRequest) -> ContextRenderResult:
        value = request.inputs.get("prior_actions", ())
        if not isinstance(value, (tuple, list)):
            raise TypeError("agent prior_actions input must be a sequence")
        envelope_chars = len(f"\n[{request.block.block_id}]\n") + 1
        content_budget = max(0, request.available_chars - envelope_chars)
        projection = project_action_history(value, max_chars=content_budget)
        return ContextRenderResult(
            projection.text,
            compacted=projection.receipt.compacted,
            receipt=_history_receipt_payload(projection.receipt),
        )

    registry.register(
        "agent.context.system",
        system,
        implementation_digest=_context_renderer_implementation_digest("agent.context.system"),
    )
    registry.register(
        "agent.context.goal",
        goal,
        implementation_digest=_context_renderer_implementation_digest("agent.context.goal"),
    )
    registry.register(
        "agent.context.observation",
        observation,
        implementation_digest=_context_renderer_implementation_digest("agent.context.observation"),
    )
    registry.register(
        "agent.context.skills",
        skills,
        implementation_digest=_context_renderer_implementation_digest("agent.context.skills"),
    )
    registry.register(
        "agent.context.memory",
        memory,
        implementation_digest=_context_renderer_implementation_digest("agent.context.memory"),
    )
    registry.register(
        "agent.context.action-history",
        action_history,
        implementation_digest=_context_renderer_implementation_digest("agent.context.action-history"),
    )
    return registry


def _agent_inputs(
    *,
    goal: AgentGoal,
    observation: AgentObservation,
    memory: AgentMemoryContext,
    skills: Iterable[AgentSkillDescription],
    prior_actions: Iterable[Mapping[str, JsonValue]],
    extra_inputs: Mapping[str, JsonValue] | None,
) -> JsonObject:
    if not isinstance(goal, AgentGoal):
        raise TypeError("agent context requires AgentGoal")
    if not isinstance(observation, AgentObservation):
        raise TypeError("agent context requires AgentObservation")
    if not isinstance(memory, AgentMemoryContext):
        raise TypeError("agent context requires AgentMemoryContext")
    skill_rows = tuple(skills)
    if any(not isinstance(skill, AgentSkillDescription) for skill in skill_rows):
        raise TypeError("agent context skills must be AgentSkillDescription values")
    history_rows = tuple(prior_actions)
    if any(not isinstance(row, Mapping) for row in history_rows):
        raise TypeError("agent prior_actions must be object mappings")
    if extra_inputs is not None and not isinstance(extra_inputs, Mapping):
        raise TypeError("agent context extra_inputs must be an object")

    inputs: dict[str, JsonValue] = {
        "goal": {
            "goal_id": goal.goal_id,
            "objective": goal.objective,
            "context": goal.context,
        },
        "observation": {
            "observation_id": observation.observation_id,
            "generation": observation.generation,
            "state": observation.state,
            "modality": observation.modality,
            "artifact_refs": observation.artifact_refs,
        },
        "memory": {
            "context_text": memory.context_text,
            "generation": memory.generation,
            "artifacts": memory.artifacts,
            "query_id": memory.query_id,
        },
        "skills": tuple({
            "skill_id": skill.skill_id,
            "category": skill.category,
            "description": skill.description,
            "arguments": skill.argument_contract,
            "mutates_world": skill.mutates_world,
            "supports_sequences": skill.supports_sequences,
            "safety_class": skill.safety_class,
        } for skill in skill_rows),
        "prior_actions": tuple(dict(row) for row in history_rows),
    }
    if extra_inputs:
        overlap = set(inputs) & set(extra_inputs)
        if overlap:
            raise ValueError(
                f"agent context extra_inputs shadow reserved inputs: {sorted(overlap)}"
            )
        inputs.update(extra_inputs)
    return freeze_json(inputs)


class AgentContextCompiler:
    """Typed Agent adapter over the generic pure ContextProgram IR."""

    def __init__(
        self,
        *,
        program: ContextProgram | None = None,
        renderers: ContextRendererRegistry | None = None,
        max_chars: int = 12_000,
    ) -> None:
        if program is not None and not isinstance(program, ContextProgram):
            raise TypeError("agent context program must be ContextProgram")
        if renderers is not None and not isinstance(renderers, ContextRendererRegistry):
            raise TypeError("agent context renderers must be ContextRendererRegistry")
        self.program = (
            default_agent_context_program(max_chars=max_chars)
            if program is None
            else program
        )
        self.renderers = (
            default_agent_context_renderers()
            if renderers is None
            else renderers
        )

    def compile(
        self,
        *,
        goal: AgentGoal,
        observation: AgentObservation,
        memory: AgentMemoryContext,
        skills: Iterable[AgentSkillDescription],
        prior_actions: Iterable[Mapping[str, JsonValue]] = (),
        extra_inputs: Mapping[str, JsonValue] | None = None,
    ) -> CompiledAgentContext:
        inputs = _agent_inputs(
            goal=goal,
            observation=observation,
            memory=memory,
            skills=skills,
            prior_actions=prior_actions,
            extra_inputs=extra_inputs,
        )
        try:
            projection = compile_context(self.program, inputs, self.renderers)
        except ContextBudgetExceeded as exc:
            raise AgentContextBudgetExceeded(
                required_chars=exc.required_chars,
                max_chars=exc.max_chars,
            ) from exc
        history = _history_receipt_from_payload(
            projection.receipts.get("prior_actions")
        )
        return CompiledAgentContext(
            schema_version="agent-context.v4",
            context_program_digest=self.program.program_digest,
            context_binding_digest=projection.binding_digest,
            text=projection.text,
            block_ids=projection.block_ids,
            omitted_block_ids=projection.omitted_block_ids,
            compacted_block_ids=projection.compacted_block_ids,
            history_projection=history,
        )


__all__ = [
    "AgentContextBudgetExceeded",
    "AgentContextCompiler",
    "CompiledAgentContext",
    "default_agent_context_program",
    "default_agent_context_renderers",
]
