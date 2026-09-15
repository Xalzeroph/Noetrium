from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable, Mapping

from noetrium_platform.foundation.kernel.kernel import canonical_bytes

from ..api.cognition import AgentGoal, AgentMemoryContext, AgentObservation, AgentSkillDescription, JsonValue
from .model_view import AgentActionHistoryProjectionReceipt, project_action_history


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
    compacted_block_ids: tuple[str, ...] = ()
    history_projection: AgentActionHistoryProjectionReceipt | None = None


class AgentPromptBudgetExceeded(ValueError):
    def __init__(self, *, required_chars: int, max_chars: int) -> None:
        self.required_chars = required_chars
        self.max_chars = max_chars
        super().__init__(
            "required agent host facts exceed model-view character envelope: "
            f"required={required_chars}, max={max_chars}; no required fact was truncated"
        )


def _render_atomic_block(block: PromptBlock) -> str:
    return f"\n[{block.block_id}]\n{block.text}\n"


def _canonical_json(value: object) -> str:
    return json.dumps(
        json.loads(canonical_bytes(value)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class AgentPromptAssembler:
    """Build a loss-explicit model view while preserving durable host truth.

    Required host facts are atomic and fail closed if they do not fit. Optional
    text blocks are admitted whole or omitted. Action history is the only block
    compacted here, and compaction keeps complete action records plus a digest
    receipt. Final token admission/output reservation is still owned by
    ``model/request``.
    """

    def __init__(self, *, max_chars: int = 12000) -> None:
        if type(max_chars) is not int or max_chars < 512:
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
        skill_rows = tuple(skills)
        history_rows = tuple(prior_actions)
        required = sorted(
            (
                PromptBlock(
                    "system",
                    "Choose one typed skill and never claim completion without state evidence.",
                    100,
                    True,
                ),
                PromptBlock(
                    "goal",
                    _canonical_json(
                        {
                            "goal_id": goal.goal_id,
                            "objective": goal.objective,
                            "context": goal.context,
                        }
                    ),
                    90,
                    True,
                ),
                PromptBlock("observation", _canonical_json(observation.state), 80, True),
                PromptBlock(
                    "skills",
                    _canonical_json(
                        tuple(
                            {
                                "skill_id": skill.skill_id,
                                "category": skill.category,
                                "description": skill.description,
                                "arguments": skill.argument_contract,
                            }
                            for skill in skill_rows
                        )
                    ),
                    70,
                    True,
                ),
            ),
            key=lambda item: (-item.priority, item.block_id),
        )
        required_rendered = tuple(_render_atomic_block(block) for block in required)
        required_chars = sum(map(len, required_rendered))
        if required_chars > self._max_chars:
            raise AgentPromptBudgetExceeded(
                required_chars=required_chars,
                max_chars=self._max_chars,
            )

        rendered = list(required_rendered)
        selected_ids = [block.block_id for block in required]
        used = required_chars
        omitted_ids: list[str] = []
        compacted_ids: list[str] = []
        history_receipt: AgentActionHistoryProjectionReceipt | None = None

        optional_entries: list[tuple[int, str, PromptBlock | None]] = [
            (50, "memory", PromptBlock("memory", memory.context_text or "(no verified memory)", 50)),
            (40, "prior_actions", None),
        ]
        optional_entries.extend((block.priority, block.block_id, block) for block in extra)
        optional_entries.sort(key=lambda item: (-item[0], item[1]))

        known_ids = set(selected_ids)
        for _, block_id, block in optional_entries:
            if block_id in known_ids:
                raise ValueError(f"duplicate agent prompt block id: {block_id}")
            known_ids.add(block_id)
            remaining = self._max_chars - used
            if block_id == "prior_actions":
                prefix = "\n[prior_actions]\n"
                suffix = "\n"
                content_budget = max(0, remaining - len(prefix) - len(suffix))
                projection = project_action_history(history_rows, max_chars=content_budget)
                history_receipt = projection.receipt
                if not projection.text:
                    if history_rows:
                        omitted_ids.append(block_id)
                    continue
                rendered_block = prefix + projection.text + suffix
                if len(rendered_block) > remaining:
                    raise RuntimeError("agent history projection exceeded its declared envelope")
                rendered.append(rendered_block)
                selected_ids.append(block_id)
                used += len(rendered_block)
                if projection.receipt.compacted:
                    compacted_ids.append(block_id)
                continue

            assert block is not None
            rendered_block = _render_atomic_block(block)
            if len(rendered_block) > remaining:
                omitted_ids.append(block_id)
                continue
            rendered.append(rendered_block)
            selected_ids.append(block_id)
            used += len(rendered_block)

        result = "".join(rendered)
        if len(result) > self._max_chars:
            raise RuntimeError("agent prompt assembler exceeded its hard budget")
        lossy = bool(omitted_ids or compacted_ids)
        return CompiledAgentPrompt(
            schema_version="agent-prompt.v2",
            text=result,
            block_ids=tuple(selected_ids),
            truncated=lossy,
            omitted_block_ids=tuple(omitted_ids),
            truncated_block_ids=(),
            compacted_block_ids=tuple(compacted_ids),
            history_projection=history_receipt,
        )


__all__ = [
    "AgentPromptAssembler",
    "AgentPromptBudgetExceeded",
    "CompiledAgentPrompt",
    "PromptBlock",
]
