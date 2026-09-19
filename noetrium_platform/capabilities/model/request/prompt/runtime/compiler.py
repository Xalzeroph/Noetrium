from __future__ import annotations

from dataclasses import dataclass

from .block_validation import PromptBlockValidator
from .blocks import PromptBlock, PromptBlockKind, PromptBlockPolicy
from .rendering import PromptBlockStat, PromptRenderer
from .runtime_contracts import ActivePromptBundle


@dataclass(frozen=True, slots=True)
class CompiledPrompt:
    bundle_digest: str
    role: str
    text: str
    dynamic_digest: str
    block_kinds: tuple[str, ...]
    block_stats: tuple[PromptBlockStat, ...]
    compiled_chars: int
    compiled_bytes: int


class PromptCompiler:
    """Thin validate -> render façade; budgeting/schema binding live in pipeline."""

    def __init__(
        self,
        validator: PromptBlockValidator | None = None,
        renderer: PromptRenderer | None = None,
    ) -> None:
        self.validator = validator or PromptBlockValidator()
        self.renderer = renderer or PromptRenderer()

    def compile(
        self,
        bundle: ActivePromptBundle,
        policy: PromptBlockPolicy,
        blocks: tuple[PromptBlock, ...],
    ) -> CompiledPrompt:
        ordered = self.validator.validate_and_order(bundle, policy, blocks)
        rendered = self.renderer.render(bundle, ordered)
        return CompiledPrompt(
            bundle.digest,
            bundle.role,
            rendered.text,
            rendered.dynamic_digest,
            rendered.block_kinds,
            rendered.block_stats,
            rendered.compiled_chars,
            rendered.compiled_bytes,
        )


def default_block_policies() -> dict[str, PromptBlockPolicy]:
    B=PromptBlockKind
    return {
        "planner": PromptBlockPolicy("planner", frozenset({B.TASK,B.VERIFIED_STATE,B.TOOL_CATALOG}), frozenset({B.TASK,B.VERIFIED_STATE,B.TOOL_CATALOG,B.MEMORY_CONTEXT,B.PRIOR_OUTCOME}), ((B.TASK,16000),(B.VERIFIED_STATE,24000),(B.TOOL_CATALOG,24000),(B.MEMORY_CONTEXT,64000),(B.PRIOR_OUTCOME,16000))),
        "semantic": PromptBlockPolicy("semantic", frozenset({B.MEMORY_CONTEXT}), frozenset({B.MEMORY_CONTEXT,B.TASK}), ((B.MEMORY_CONTEXT,96000),(B.TASK,16000))),
        "meta": PromptBlockPolicy("meta", frozenset({B.ARCHITECTURE_OBSERVATION}), frozenset({B.ARCHITECTURE_OBSERVATION}), ((B.ARCHITECTURE_OBSERVATION,96000),)),
        "diagnostic": PromptBlockPolicy("diagnostic", frozenset({B.FAILURE_EVIDENCE}), frozenset({B.FAILURE_EVIDENCE}), ((B.FAILURE_EVIDENCE,96000),)),
    }
