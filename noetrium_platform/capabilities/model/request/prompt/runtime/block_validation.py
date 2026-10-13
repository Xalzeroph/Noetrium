from __future__ import annotations

from .blocks import PromptBlock, PromptBlockKind, PromptBlockPolicy
from .runtime_contracts import ActivePromptBundle


class PromptBlockValidator:
    """Pure authority for role/block admissibility, ordering, and per-kind size limits."""

    def validate_and_order(
        self,
        bundle: ActivePromptBundle,
        policy: PromptBlockPolicy,
        blocks: tuple[PromptBlock, ...],
    ) -> tuple[PromptBlock, ...]:
        if bundle.role != policy.role:
            raise ValueError("prompt role/policy mismatch")
        kinds = [block.kind for block in blocks]
        if len(kinds) != len(set(kinds)):
            raise ValueError("duplicate dynamic prompt block")
        missing = policy.required - set(kinds)
        unknown = set(kinds) - policy.allowed
        if missing:
            raise ValueError(
                f"missing required prompt blocks: {sorted(x.value for x in missing)}"
            )
        if unknown:
            raise ValueError(
                f"forbidden prompt blocks: {sorted(x.value for x in unknown)}"
            )
        ordered = tuple(sorted(blocks, key=lambda block: (block.sequence, block.kind.value)))
        for block in ordered:
            if len(block.content) > policy.max_chars(block.kind):
                raise ValueError(f"prompt block too large: {block.kind.value}")
        return ordered
