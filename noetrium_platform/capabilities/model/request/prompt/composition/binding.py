from __future__ import annotations

from noetrium_platform.capabilities.model.request.api import ModelRequestRecorderPort
from noetrium_platform.capabilities.model.request.prompt.api import (
    PromptBoundRequest,
    PromptBodyContext,
    PromptDynamicBlock,
    PromptRequestBindingPort,
    PromptRequestBodyBuilder,
)
from noetrium_platform.capabilities.model.request.prompt.runtime import (
    OutputSchemaRegistry,
    PromptBlock,
    PromptBlockKind,
    PromptBlockPolicy,
    PromptCompilePipeline,
    PromptRegistry,
    PromptRequestBuildTransaction,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity


class FrozenPromptRequestBinding(PromptRequestBindingPort):
    """Platform composition adapter freezing one prompt generation and schema."""

    def __init__(
        self,
        *,
        registry: PromptRegistry,
        prompt_id: str,
        policy: PromptBlockPolicy,
        schemas: OutputSchemaRegistry,
        model_requests: ModelRequestRecorderPort,
    ) -> None:
        resolution = registry.resolve(prompt_id)
        if resolution.bundle.role != policy.role:
            raise ValueError("prompt policy role does not match frozen prompt bundle")
        schema = schemas.require(resolution.bundle.output_schema)
        self._resolution = resolution
        self._policy = policy
        self._schemas = OutputSchemaRegistry((schema,))
        self._model_requests = model_requests
        self._transaction = PromptRequestBuildTransaction(PromptCompilePipeline())

    @property
    def prompt_generation_id(self) -> str:
        return self._resolution.generation_id

    @property
    def prompt_id(self) -> str:
        return self._resolution.bundle.prompt_id

    @property
    def prompt_digest(self) -> str:
        return self._resolution.bundle.digest

    def build(
        self,
        *,
        blocks: tuple[PromptDynamicBlock, ...],
        request_id: str,
        context: ExecutionContext,
        model: ImmutableModelIdentity,
        body_builder: PromptRequestBodyBuilder,
        source_artifact_refs: tuple[str, ...] = (),
        source_state_refs: tuple[str, ...] = (),
    ) -> PromptBoundRequest:
        runtime_blocks = tuple(
            PromptBlock(
                PromptBlockKind(block.kind),
                block.content,
                block.source_digest,
                block.sequence,
            )
            for block in blocks
        )

        def build_body(resolution, compilation) -> dict[str, object]:
            value = body_builder(PromptBodyContext(
                prompt_id=resolution.bundle.prompt_id,
                prompt_digest=resolution.bundle.digest,
                role=resolution.bundle.role,
                model_id=model.model_id,
                output_schema=resolution.bundle.output_schema,
                compiled_text=compilation.compiled.text,
                temperature=resolution.bundle.temperature,
                top_p=resolution.bundle.top_p,
                max_output_tokens=resolution.bundle.max_output_tokens,
            ))
            if not isinstance(value, dict):
                return dict(value)
            return value

        bound = self._transaction.build(
            resolution=self._resolution,
            prompt_id=self._resolution.bundle.prompt_id,
            policy=self._policy,
            blocks=runtime_blocks,
            schemas=self._schemas,
            request_id=request_id,
            context=context,
            model=model,
            body_builder=build_body,
            model_requests=self._model_requests,
            source_artifact_refs=source_artifact_refs,
            source_state_refs=source_state_refs,
        )
        return PromptBoundRequest(
            request=bound.model_request,
            body=bound.request_body,
            prompt_generation_id=bound.resolution.generation_id,
            prompt_id=bound.resolution.bundle.prompt_id,
            prompt_digest=bound.resolution.bundle.digest,
        )


__all__ = ["FrozenPromptRequestBinding"]
