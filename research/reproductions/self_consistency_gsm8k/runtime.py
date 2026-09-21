from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.capabilities.model.serving.endpoint import (
    AdaptiveModelEndpointPoolPort,
)
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    ImmutableModelIdentity,
    canonical_bytes,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodEvent,
    MethodRunResult,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.composition.machine_binding import (
    bind_machine_method_runtime,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from research.benchmarks.gsm8k import GSM8KMaterializedTask
from research.reproductions.chain_of_thought_gsm8k.prompt import (
    COT_GSM8K_PROMPT_BUNDLE_ID,
    COT_GSM8K_PROMPT_DIGEST,
)

from .program import (
    SELF_CONSISTENCY_GSM8K_METHOD_PROGRAM,
    self_consistency_gsm8k_initial_state,
)


@dataclass(frozen=True, slots=True)
class SelfConsistencyGSM8KModelBinding:
    served_model_name: str
    model: ImmutableModelIdentity
    prompt_generation_id: str
    max_tokens: int = 512
    base_seed: int = 0
    pool_timeout_seconds: float = 180.0

    def __post_init__(self) -> None:
        if not self.served_model_name.strip():
            raise ValueError("Self-Consistency served model name is required")
        if not isinstance(self.model, ImmutableModelIdentity):
            raise TypeError("Self-Consistency model identity must be ImmutableModelIdentity")
        if not self.prompt_generation_id.strip():
            raise ValueError("Self-Consistency prompt generation id is required")
        if type(self.max_tokens) is not int or self.max_tokens < 1:
            raise ValueError("Self-Consistency max_tokens must be positive")
        if type(self.base_seed) is not int:
            raise TypeError("Self-Consistency base_seed must be integer")
        if self.pool_timeout_seconds <= 0:
            raise ValueError("Self-Consistency pool timeout must be positive")


@dataclass(frozen=True, slots=True)
class SelfConsistencyInvocation:
    sample_index: int
    deployment_id: str
    deployment_generation: str
    endpoint_request_digest: str
    request_envelope_digest: str
    response_digest: str
    input_tokens: int | None
    output_tokens: int | None
    finish_reason: str | None


@dataclass(frozen=True, slots=True)
class SelfConsistencyGSM8KEpisodeResult:
    method_result: MethodRunResult
    invocations: tuple[SelfConsistencyInvocation, ...]


class PooledSelfConsistencyReasoner:
    """Paper-private sampling semantics over the platform endpoint-pool scheduler."""

    def __init__(
        self,
        pool: AdaptiveModelEndpointPoolPort,
        binding: SelfConsistencyGSM8KModelBinding,
    ) -> None:
        self._pool = pool
        self._binding = binding
        self._invocations: list[SelfConsistencyInvocation] = []

    @property
    def invocations(self) -> tuple[SelfConsistencyInvocation, ...]:
        return tuple(self._invocations)

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        prompt = request.view.get("prompt")
        prompt_digest = request.view.get("prompt_digest")
        sample_index = request.view.get("sample_index")
        sampling = request.view.get("sampling")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Self-Consistency reasoner requires materialized prompt")
        if prompt_digest != COT_GSM8K_PROMPT_DIGEST:
            raise ValueError("Self-Consistency prompt authority drift")
        if type(sample_index) is not int or sample_index < 0:
            raise ValueError("Self-Consistency sample_index is invalid")
        if not isinstance(sampling, dict):
            raise TypeError("Self-Consistency sampling view must be a mapping")
        temperature = sampling.get("temperature")
        top_k = sampling.get("top_k")
        if not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
            raise TypeError("Self-Consistency temperature must be numeric")
        if type(top_k) is not int or top_k < 1:
            raise ValueError("Self-Consistency top_k must be positive")

        body = {
            "model": self._binding.served_model_name,
            "messages": ({"role": "user", "content": prompt},),
            "temperature": float(temperature),
            "top_k": top_k,
            "max_tokens": self._binding.max_tokens,
            "seed": self._binding.base_seed + sample_index,
        }
        body_bytes = canonical_bytes(body)
        request_id = (
            f"{request.context.run_id}:{request.context.task_id or 'task'}:"
            f"{request.agent_id}:sample-{sample_index:02d}"
        )
        prompt_bytes = prompt.encode("utf-8")
        envelope = ModelRequestEnvelope(
            schema_version="model-request.v1",
            request_id=request_id,
            context=request.context,
            role=request.agent_id,
            model=self._binding.model,
            prompt_generation_id=self._binding.prompt_generation_id,
            prompt_id=COT_GSM8K_PROMPT_BUNDLE_ID,
            prompt_digest=COT_GSM8K_PROMPT_DIGEST,
            request_body=ArtifactBlobRef(
                canonical_digest(body),
                len(body_bytes),
                "application/json",
            ),
            compiled_prompt=ArtifactBlobRef(
                hashlib.sha256(prompt_bytes).hexdigest(),
                len(prompt_bytes),
                "text/plain",
            ),
            source_artifact_refs=(
                f"prompt:{COT_GSM8K_PROMPT_DIGEST}",
                f"task:{request.context.task_id or 'unknown'}",
                f"sample:{sample_index}",
            ),
        )
        dispatch = self._pool.complete(envelope, body)
        endpoint_request = dispatch.request
        response = dispatch.response
        endpoint_request_digest = endpoint_request.digest()
        effect = EffectReceipt(
            effect_id=f"model:{request_id}",
            request_digest=endpoint_request_digest,
            effect_class=EffectClass.NON_IDEMPOTENT,
            certainty=EffectCertainty.EFFECT_CONFIRMED,
            provider_instance_id=endpoint_request.deployment_id,
            verification_required=False,
            before_artifact=envelope.envelope_digest,
            after_artifact=response.response_digest,
            provider_receipt=response.response_digest,
        )
        invocation = SelfConsistencyInvocation(
            sample_index=sample_index,
            deployment_id=endpoint_request.deployment_id,
            deployment_generation=endpoint_request.deployment_generation,
            endpoint_request_digest=endpoint_request_digest,
            request_envelope_digest=envelope.envelope_digest,
            response_digest=response.response_digest,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            finish_reason=response.finish_reason,
        )
        self._invocations.append(invocation)
        return MethodAgentResult(
            value=response.text,
            events=(
                MethodEvent(
                    "model.invocation",
                    {
                        "sample_index": sample_index,
                        "deployment_id": endpoint_request.deployment_id,
                        "deployment_generation": endpoint_request.deployment_generation,
                        "request_id": request_id,
                        "request_digest": endpoint_request_digest,
                        "response_digest": response.response_digest,
                        "replica_set_digest": dispatch.replica_set_digest,
                        "selection_sequence": dispatch.selection_sequence,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "finish_reason": response.finish_reason,
                    },
                ),
            ),
            effect_receipts=(effect,),
        )


def run_self_consistency_gsm8k_episode(
    task: GSM8KMaterializedTask,
    *,
    endpoint_pool: AdaptiveModelEndpointPoolPort,
    binding: SelfConsistencyGSM8KModelBinding,
    run_id: str,
    state_root: str | Path,
) -> SelfConsistencyGSM8KEpisodeResult:
    if not isinstance(task, GSM8KMaterializedTask):
        raise TypeError("Self-Consistency task must be GSM8KMaterializedTask")
    reasoner = PooledSelfConsistencyReasoner(endpoint_pool, binding)
    execution = ExecutionContext(
        run_id,
        f"trace:{run_id}",
        f"span:{task.task_id}",
        task_id=task.task_id,
    )
    runtime = bind_machine_method_runtime(
        SELF_CONSISTENCY_GSM8K_METHOD_PROGRAM,
        MethodRuntimeContext(execution, agent_loop=reasoner),
        state_root=Path(state_root),
        machine_id=f"method:{run_id}:{task.task_id}",
    )
    result = UniversalMethodMachine(max_steps=128).run(
        SELF_CONSISTENCY_GSM8K_METHOD_PROGRAM,
        runtime=runtime,
        input_value={
            "task_id": task.task_id,
            "question_digest": task.record.question_digest,
        },
        initial_state=self_consistency_gsm8k_initial_state(
            task_id=task.task_id,
            question=task.question,
        ),
    )
    if len(reasoner.invocations) != 40:
        raise RuntimeError(
            "Self-Consistency requires 40 model invocations, "
            f"got {len(reasoner.invocations)}; "
            f"status={result.status.value}; failure={result.failure!r}; "
            f"failure_code={result.failure_code!r}; diagnostics={result.diagnostics!r}"
        )
    return SelfConsistencyGSM8KEpisodeResult(
        method_result=result,
        invocations=reasoner.invocations,
    )


__all__ = [
    "PooledSelfConsistencyReasoner",
    "SelfConsistencyGSM8KEpisodeResult",
    "SelfConsistencyGSM8KModelBinding",
    "SelfConsistencyInvocation",
    "run_self_consistency_gsm8k_episode",
]
