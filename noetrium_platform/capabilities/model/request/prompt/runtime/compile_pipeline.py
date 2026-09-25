from __future__ import annotations

from dataclasses import dataclass

from .blocks import PromptBlock, PromptBlockPolicy
from .compiler import CompiledPrompt, PromptCompiler
from .runtime_contracts import PromptResolution
from .schema import OutputSchemaRegistry, OutputSchemaSpec


@dataclass(frozen=True, slots=True)
class PromptCompilationReceipt:
    generation_id: str
    prompt_id: str
    bundle_digest: str
    schema_id: str
    schema_digest: str
    compiled: CompiledPrompt


class PromptCompilePipeline:
    """Strict no-degradation Prompt compilation transaction."""

    def __init__(self, compiler: PromptCompiler | None = None) -> None:
        self.compiler = compiler or PromptCompiler()

    def compile(
        self,
        *,
        resolution: PromptResolution,
        policy: PromptBlockPolicy,
        blocks: tuple[PromptBlock, ...],
        schemas: OutputSchemaRegistry,
    ) -> PromptCompilationReceipt:
        bundle = resolution.bundle
        schema = schemas.require(bundle.output_schema)
        compiled = self.compiler.compile(bundle, policy, blocks)
        return PromptCompilationReceipt(
            generation_id=resolution.generation_id,
            prompt_id=bundle.prompt_id,
            bundle_digest=bundle.digest,
            schema_id=schema.schema_id,
            schema_digest=schema.digest(),
            compiled=compiled,
        )
