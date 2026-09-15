from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable, Mapping

from noetrium_platform.foundation.kernel.kernel import canonical_bytes

from ..api.cognition import AgentGoal, AgentMemoryContext, AgentObservation, AgentSkillDescription, JsonValue


@dataclass(frozen=True, slots=True)
class PromptBlock:
    block_id: str
    text: str
    priority: int = 0
    required: bool = False

    def __post_init__(self) -> None:
        if not self.block_id.strip() or not self.text.strip():
            raise ValueError("prompt block identity and text are required")


@dataclass(frozen=True, slots=True)
class CompiledAgentPrompt:
    schema_version: str
    text: str
    block_ids: tuple[str, ...]
    truncated: bool
    omitted_block_ids: tuple[str, ...] = ()
    truncated_block_ids: tuple[str, ...] = ()


_PROMPT_TRUNCATION_MARKER = "\n...[omitted middle context]...\n"


def _bounded_prompt_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Keep a deterministic head/tail view with explicit loss evidence."""

    if len(text) <= max_chars:
        return text, False
    if max_chars <= len(_PROMPT_TRUNCATION_MARKER):
        return _PROMPT_TRUNCATION_MARKER[:max_chars], True
    remaining = max_chars - len(_PROMPT_TRUNCATION_MARKER)
    head = (remaining + 1) // 2
    tail = remaining // 2
    return text[:head] + _PROMPT_TRUNCATION_MARKER + text[-tail:], True


def _render_block_with_budget(block: PromptBlock, budget: int) -> tuple[str, bool]:
    """Render one block without ever slicing the assembled prompt."""

    prefix = f"\n[{block.block_id}]\n"
    suffix = "\n"
    content_budget = max(0, budget - len(prefix) - len(suffix))
    if content_budget == 0:
        return (prefix + suffix)[:budget], True
    content, truncated = _bounded_prompt_text(block.text, content_budget)
    return prefix + content + suffix, truncated


class AgentPromptAssembler:
    """Structured, deterministic context assembly with explicit omission evidence.

    Required blocks always retain a labeled representation. Optional blocks are
    admitted by priority and never consume the reserved envelope of later
    required state. The assembler is domain-neutral: it does not invent skills,
    retrieve a skill library, or execute model-produced code.
    """

    def __init__(self, *, max_chars: int = 12000) -> None:
        if max_chars < 512:
            raise ValueError("agent prompt budget is too small")
        self._max_chars = max_chars

    def compile(
        self,
        *,
        goal: AgentGoal,
        observation: AgentObservation,
        memory: AgentMemoryContext,
        skills: Iterable[AgentSkillDescription],
        prior_actions: Iterable[Mapping[str, JsonValue]] = (),
        extra: Iterable[PromptBlock] = (),
    ) -> CompiledAgentPrompt:
        blocks = [
            PromptBlock("system", "Choose one typed skill and never claim completion without state evidence.", 100, True),
            PromptBlock("goal", json.dumps(json.loads(canonical_bytes({"goal_id": goal.goal_id, "objective": goal.objective, "context": goal.context})), sort_keys=True), 90, True),
            PromptBlock("observation", json.dumps(json.loads(canonical_bytes(observation.state)), ensure_ascii=False, sort_keys=True), 80, True),
            PromptBlock("skills", json.dumps([{"skill_id": skill.skill_id, "category": skill.category, "description": skill.description, "arguments": skill.argument_contract} for skill in skills], ensure_ascii=False, sort_keys=True), 70, True),
            PromptBlock("memory", memory.context_text or "(no verified memory)", 50),
            PromptBlock("prior_actions", json.dumps(json.loads(canonical_bytes(tuple(prior_actions))), ensure_ascii=False, sort_keys=True), 40),
            *tuple(extra),
        ]
        ordered = sorted(blocks, key=lambda item: (-item.priority, item.block_id))
        required = [block for block in ordered if block.required]
        optional = [block for block in ordered if not block.required]
        selected: list[PromptBlock] = []
        rendered: list[str] = []
        used = 0
        truncated = False
        omitted_block_ids: list[str] = []
        truncated_block_ids: list[str] = []

        # Reserve each later required envelope before admitting current content.
        required_minimum = {
            block.block_id: len(f"\n[{block.block_id}]\n\n")
            for block in required
        }
        for index, block in enumerate(required):
            future = sum(required_minimum[item.block_id] for item in required[index + 1 :])
            budget = max(1, self._max_chars - used - future)
            rendered_block, was_truncated = _render_block_with_budget(block, budget)
            selected.append(block)
            rendered.append(rendered_block)
            used += len(rendered_block)
            truncated = truncated or was_truncated
            if was_truncated:
                truncated_block_ids.append(block.block_id)

        for block in optional:
            remaining = self._max_chars - used
            minimum = len(f"\n[{block.block_id}]\n\n") + 1
            if remaining < minimum:
                truncated = True
                omitted_block_ids.append(block.block_id)
                continue
            rendered_block, was_truncated = _render_block_with_budget(block, remaining)
            if len(rendered_block) > remaining:
                truncated = True
                omitted_block_ids.append(block.block_id)
                continue
            selected.append(block)
            rendered.append(rendered_block)
            used += len(rendered_block)
            truncated = truncated or was_truncated
            if was_truncated:
                truncated_block_ids.append(block.block_id)

        result = "".join(rendered)
        if len(result) > self._max_chars:
            raise RuntimeError("agent prompt assembler exceeded its hard budget")
        return CompiledAgentPrompt(
            "agent-prompt.v1",
            result,
            tuple(block.block_id for block in selected),
            truncated or len(selected) != len(blocks),
            tuple(omitted_block_ids),
            tuple(truncated_block_ids),
        )


__all__ = ["AgentPromptAssembler", "CompiledAgentPrompt", "PromptBlock"]
