from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity, JsonObject, freeze_json
from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope, ModelRequestRecorderPort

from .blocks import PromptBlock, PromptBlockPolicy
from .compile_pipeline import PromptCompilationReceipt, PromptCompilePipeline
from .execution_contract import PromptExecutionContract, build_execution_contract
from .request_contract import PromptRequestContract, build_prompt_request_contract
from .runtime import PromptRegistry
from .runtime_contracts import PromptResolution
from .schema import OutputSchemaRegistry
from noetrium_platform.capabilities.model.request.prompt.api import PromptTraceStage
from .trace import PromptRequestTrace


RequestBodyBuilder = Callable[[PromptResolution, PromptCompilationReceipt], dict[str, object]]


@dataclass(frozen=True, slots=True)
class PromptBoundRequest:
    resolution: PromptResolution
    compilation: PromptCompilationReceipt
    request_body: JsonObject
    request_contract: PromptRequestContract
    execution_contract: PromptExecutionContract
    model_request: ModelRequestEnvelope


class PromptRequestBuildTransaction:
    """Atomic identity transaction for one prompt request build.

    Registry resolution happens exactly once. Everything else derives from that
    immutable resolution so a concurrent prompt generation switch cannot create
    a mixed-generation request contract.
    """

    def __init__(self, pipeline: PromptCompilePipeline) -> None:
        if not isinstance(pipeline, PromptCompilePipeline):
            raise TypeError("prompt request build transaction requires PromptCompilePipeline")
        self.pipeline = pipeline

    def build(
        self,
        *,
        registry: PromptRegistry | None = None,
        resolution: PromptResolution | None = None,
        prompt_id: str,
        policy: PromptBlockPolicy,
        blocks: tuple[PromptBlock, ...],
        schemas: OutputSchemaRegistry,
        request_id: str,
        context: ExecutionContext,
        model: ImmutableModelIdentity,
        body_builder: RequestBodyBuilder,
        model_requests: ModelRequestRecorderPort,
        trace: PromptRequestTrace | None = None,
        source_artifact_refs: tuple[str, ...] = (),
        source_state_refs: tuple[str, ...] = (),
    ) -> PromptBoundRequest:
        if (registry is None) == (resolution is None):
            raise ValueError("provide exactly one prompt registry or frozen prompt resolution")
        resolution = resolution if resolution is not None else registry.resolve(prompt_id)  # type: ignore[union-attr]
        if resolution.bundle.prompt_id != prompt_id:
            raise ValueError("frozen prompt resolution does not match prompt_id")
        if trace is not None:
            trace.mark(PromptTraceStage.COMPILE_STARTED, bundle=resolution.bundle.digest)
        compilation = self.pipeline.compile(
            resolution=resolution,
            policy=policy,
            blocks=blocks,
            schemas=schemas,
        )
        if trace is not None:
            trace.mark(
                PromptTraceStage.COMPILE_COMPLETED,
                bundle=resolution.bundle.digest,
                compiled_bytes=compilation.compiled.compiled_bytes,
                block_count=len(compilation.compiled.block_stats),
                block_bytes=tuple((x.kind,x.bytes) for x in compilation.compiled.block_stats),
            )
        body = body_builder(resolution, compilation)
        if not isinstance(body, dict):
            raise TypeError("prompt request body builder must return a dict")
        body = freeze_json(body)

        request_contract = build_prompt_request_contract(
            request_id=request_id,
            resolution=resolution,
            model=model,
            request_body=body,
        )
        execution_contract = build_execution_contract(
            request_id=request_id,
            compilation=compilation,
            resolution=resolution,
            model=model,
            request_body=body,
        )
        model_request = model_requests.record(
            request_id=request_id,
            context=context,
            role=resolution.bundle.role,
            model=model,
            prompt_generation_id=resolution.generation_id,
            prompt_id=resolution.bundle.prompt_id,
            prompt_digest=resolution.bundle.digest,
            request_body=body,
            compiled_prompt_text=compilation.compiled.text,
            tool_schema_bundle=body.get("tools"),
            source_artifact_refs=source_artifact_refs,
            source_state_refs=source_state_refs,
        )
        model_requests.verify_visible_request(model_request, body)
        durable_body = freeze_json(model_requests.reconstruct_request_body(model_request))
        return PromptBoundRequest(
            resolution=resolution,
            compilation=compilation,
            request_body=durable_body,
            request_contract=request_contract,
            execution_contract=execution_contract,
            model_request=model_request,
        )
