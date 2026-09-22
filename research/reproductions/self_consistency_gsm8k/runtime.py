from __future__ import annotations
from noetrium_platform.composition.method_runtime import bind_standard_method_runtime

import argparse
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import time

from noetrium_platform.capabilities.model.request.api import (
    ModelRequestRecorderPort,
)
from noetrium_platform.composition.model_requests import (
    build_directory_model_request_recorder,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointDispatchPoolPort,
    OperationalModelEndpointReplicaSet,
)
from noetrium_platform.capabilities.model.serving.endpoint.composition import (
    build_adaptive_operational_endpoint_pool,
)
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionRegistry
from noetrium_platform.foundation.kernel.concurrency.composition import (
    build_concurrency_runtime,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    ImmutableModelIdentity,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodEvent,
    MethodEvidencePort,
    MethodEvidenceStatus,
    MethodRunResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.providers import DirectoryEventMethodEvidence
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from research.benchmarks.gsm8k import (
    GSM8KMaterializedTask,
    materialize_archived_gsm8k_test,
    normalize_gsm8k_numeric_answer,
)
from research.runtime.external_substitute import (
    ExternalSubstituteModelDeployment,
    load_external_substitute_model_deployment,
)
from research.reproductions.chain_of_thought_gsm8k.prompt import (
    COT_GSM8K_PROMPT_BUNDLE_ID,
    COT_GSM8K_PROMPT_DIGEST,
)

from .fidelity import SELF_CONSISTENCY_GSM8K_FIDELITY
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
    disable_thinking: bool = True

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
        if type(self.disable_thinking) is not bool:
            raise TypeError("Self-Consistency disable_thinking must be boolean")


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
        pool: ModelEndpointDispatchPoolPort,
        binding: SelfConsistencyGSM8KModelBinding,
        recorder: ModelRequestRecorderPort,
    ) -> None:
        if not isinstance(recorder, ModelRequestRecorderPort):
            raise TypeError("Self-Consistency reasoner requires ModelRequestRecorderPort")
        self._pool = pool
        self._binding = binding
        self._recorder = recorder
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
        if not isinstance(sampling, Mapping):
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
        if self._binding.disable_thinking:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        request_id = (
            f"{request.context.run_id}:{request.context.task_id or 'task'}:"
            f"{request.agent_id}:sample-{sample_index:02d}"
        )
        envelope = self._recorder.record(
            request_id=request_id,
            context=request.context,
            role=request.agent_id,
            model=self._binding.model,
            prompt_generation_id=self._binding.prompt_generation_id,
            prompt_id=COT_GSM8K_PROMPT_BUNDLE_ID,
            prompt_digest=COT_GSM8K_PROMPT_DIGEST,
            request_body=body,
            compiled_prompt_text=prompt,
            source_artifact_refs=(
                f"prompt:{COT_GSM8K_PROMPT_DIGEST}",
                f"task:{request.context.task_id or 'unknown'}",
                f"sample:{sample_index}",
            ),
        )
        self._recorder.verify_visible_request(envelope, body)
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
    endpoint_pool: ModelEndpointDispatchPoolPort,
    binding: SelfConsistencyGSM8KModelBinding,
    run_id: str,
    state_root: str | Path,
    evidence: MethodEvidencePort,
    recorder: ModelRequestRecorderPort,
    runtime_binding_digest: str,
) -> SelfConsistencyGSM8KEpisodeResult:
    if not isinstance(task, GSM8KMaterializedTask):
        raise TypeError("Self-Consistency task must be GSM8KMaterializedTask")
    if not isinstance(evidence, MethodEvidencePort):
        raise TypeError("Self-Consistency episode requires MethodEvidencePort")
    if not isinstance(recorder, ModelRequestRecorderPort):
        raise TypeError("Self-Consistency episode requires ModelRequestRecorderPort")
    if (
        type(runtime_binding_digest) is not str
        or len(runtime_binding_digest) != 64
        or any(char not in "0123456789abcdef" for char in runtime_binding_digest)
    ):
        raise ValueError("Self-Consistency runtime_binding_digest must be SHA-256")
    reasoner = PooledSelfConsistencyReasoner(endpoint_pool, binding, recorder)
    execution = ExecutionContext(
        run_id,
        f"trace:{run_id}",
        f"span:{task.record.task_id}",
        task_id=task.record.task_id,
    )
    runtime = bind_standard_method_runtime(
        SELF_CONSISTENCY_GSM8K_METHOD_PROGRAM,
        MethodRuntimeContext(
            execution,
            agent_loop=reasoner,
            evidence=evidence,
            runtime_binding_digest=runtime_binding_digest,
        ),
        state_root=Path(state_root),
        machine_id=f"method:{run_id}:{task.record.task_id}",
    )
    result = UniversalMethodMachine(max_steps=128).run(
        SELF_CONSISTENCY_GSM8K_METHOD_PROGRAM,
        runtime=runtime,
        input_value={
            "task_id": task.record.task_id,
            "question_digest": task.record.question_digest,
        },
        initial_state=self_consistency_gsm8k_initial_state(
            task_id=task.record.task_id,
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


_SHA40 = re.compile(r"[0-9a-f]{40}\Z")


def _require_source_sha(value: str) -> str:
    if _SHA40.fullmatch(value) is None:
        raise ValueError("experiment source SHA must be lowercase Git SHA-1")
    return value


def _load_substitute_deployments(
    paths: tuple[Path, ...],
) -> tuple[ExternalSubstituteModelDeployment, ...]:
    if not paths:
        raise ValueError("Self-Consistency substitute run requires model identity receipts")
    deployments = tuple(
        load_external_substitute_model_deployment(path)
        for path in paths
    )
    if len({row.deployment_id for row in deployments}) != len(deployments):
        raise ValueError("Self-Consistency substitute deployments must be unique")
    model_digests = {row.model_identity_digest for row in deployments}
    if len(model_digests) != 1:
        raise ValueError("Self-Consistency substitute replicas have model identity drift")
    return tuple(sorted(deployments, key=lambda row: row.deployment_id))


def _histogram(samples: object) -> tuple[tuple[str, int], ...]:
    if not isinstance(samples, tuple):
        return ()
    counts: dict[str, int] = {}
    for row in samples:
        if isinstance(row, Mapping):
            answer = row.get("answer")
            if isinstance(answer, str) and answer:
                counts[answer] = counts.get(answer, 0) + 1
    return tuple(sorted(counts.items()))


def _run_substitute_task(
    task: GSM8KMaterializedTask,
    *,
    endpoint_pool: ModelEndpointDispatchPoolPort,
    model: ImmutableModelIdentity,
    served_model_name: str,
    output_root: Path,
    runtime_binding_digest: str,
    max_tokens: int,
    base_seed: int,
    timeout_s: float,
    disable_thinking: bool,
) -> dict[str, object]:
    task_root = output_root / "tasks" / task.record.task_id.replace(":", "_")
    task_root.mkdir(parents=True, exist_ok=True)
    started = time.time()
    run_id = f"self-consistency-qwen3-8b-substitute:{task.record.task_id}"
    recorder = build_directory_model_request_recorder(task_root / "model-requests")
    binding = SelfConsistencyGSM8KModelBinding(
        served_model_name=served_model_name,
        model=model,
        prompt_generation_id=COT_GSM8K_PROMPT_BUNDLE_ID,
        max_tokens=max_tokens,
        base_seed=base_seed + task.record.index * 1000,
        pool_timeout_seconds=timeout_s,
        disable_thinking=disable_thinking,
    )
    try:
        episode = run_self_consistency_gsm8k_episode(
            task,
            endpoint_pool=endpoint_pool,
            binding=binding,
            run_id=run_id,
            state_root=task_root / "machine",
            evidence=DirectoryEventMethodEvidence(task_root / "evidence"),
            recorder=recorder,
            runtime_binding_digest=runtime_binding_digest,
        )
        result = episode.method_result
        request_record_count = len(tuple((task_root / "model-requests" / "requests").glob("*.json")))
        if request_record_count != SELF_CONSISTENCY_GSM8K_FIDELITY.reasoning_path_count:
            raise RuntimeError(
                "Self-Consistency durable model-request cardinality drift: "
                f"{request_record_count}"
            )
        if result.status is not MethodRunStatus.SUCCEEDED:
            raise RuntimeError(
                f"Self-Consistency method status={result.status.value}: {result.failure}"
            )
        if result.evidence_status is not MethodEvidenceStatus.COMPLETE:
            raise RuntimeError(
                "Self-Consistency evidence is incomplete: "
                f"{result.evidence_status.value}"
            )
        if not isinstance(result.value, Mapping):
            raise TypeError("Self-Consistency result must be a mapping")
        selected = result.value.get("selected_answer")
        votes = result.value.get("selected_vote_count")
        samples = result.value.get("samples")
        if not isinstance(selected, str) or not selected:
            raise ValueError("Self-Consistency result selected answer is missing")
        if type(votes) is not int or votes <= 0:
            raise ValueError("Self-Consistency result selected vote count is invalid")
        gold = normalize_gsm8k_numeric_answer(task.final_answer)
        deployment_counts: dict[str, int] = {}
        for invocation in episode.invocations:
            deployment_counts[invocation.deployment_id] = (
                deployment_counts.get(invocation.deployment_id, 0) + 1
            )
        row: dict[str, object] = {
            "task_id": task.record.task_id,
            "run_id": run_id,
            "status": result.status.value,
            "evidence_status": result.evidence_status.value,
            "run_digest": result.run_digest,
            "question_digest": task.record.question_digest,
            "answer_digest": task.record.answer_digest,
            "content_digest": task.record.content_digest,
            "gold_final_answer": gold,
            "selected_answer": selected,
            "selected_vote_count": votes,
            "answer_histogram": _histogram(samples),
            "correct": selected == gold,
            "model_call_count": len(episode.invocations),
            "model_request_record_count": request_record_count,
            "deployment_call_counts": tuple(sorted(deployment_counts.items())),
            "invocations": tuple(asdict(item) for item in episode.invocations),
            "effect_receipt_count": len(result.effect_receipts),
            "step_count": result.step_count,
            "duration_seconds": time.time() - started,
            "failure_class": None,
            "failure": None,
        }
    except Exception as exc:
        row = {
            "task_id": task.record.task_id,
            "run_id": run_id,
            "status": "failed",
            "evidence_status": "incomplete",
            "question_digest": task.record.question_digest,
            "answer_digest": task.record.answer_digest,
            "content_digest": task.record.content_digest,
            "gold_final_answer": normalize_gsm8k_numeric_answer(task.final_answer),
            "selected_answer": None,
            "selected_vote_count": None,
            "answer_histogram": (),
            "correct": False,
            "model_call_count": None,
            "model_request_record_count": None,
            "deployment_call_counts": (),
            "invocations": (),
            "effect_receipt_count": None,
            "step_count": None,
            "duration_seconds": time.time() - started,
            "failure_class": "model-or-runtime",
            "failure": f"{type(exc).__qualname__}: {exc}",
        }
    (task_root / "episode.json").write_text(
        json.dumps(row, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return row


def run_external_qwen_substitute_pool(
    *,
    benchmark_path: Path,
    model_identity_paths: tuple[Path, ...],
    output_root: Path,
    source_sha: str,
    start: int,
    count: int,
    max_tokens: int = 512,
    base_seed: int = 0,
    per_replica_capacity: int = 1,
    task_concurrency: int = 4,
    timeout_s: float = 180.0,
    disable_thinking: bool = True,
) -> dict[str, object]:
    """Run real GSM8K Self-Consistency on substitute replicas without claim status."""

    source_sha = _require_source_sha(source_sha)
    if start < 0 or count <= 0:
        raise ValueError("Self-Consistency task start/count must be positive bounds")
    if max_tokens <= 0 or per_replica_capacity <= 0 or task_concurrency <= 0:
        raise ValueError("Self-Consistency runtime capacities must be positive")
    if timeout_s <= 0:
        raise ValueError("Self-Consistency timeout must be positive")

    materialized = materialize_archived_gsm8k_test(benchmark_path)
    selected = materialized.tasks[start : start + count]
    if len(selected) != count:
        raise ValueError("requested task range exceeds GSM8K test cut")
    deployments = _load_substitute_deployments(model_identity_paths)
    model = deployments[0].model
    served_model_names = {row.served_model_name for row in deployments}
    if len(served_model_names) != 1:
        raise ValueError("Self-Consistency substitute replicas have served-model-name drift")
    served_model_name = next(iter(served_model_names))
    replicas = OperationalModelEndpointReplicaSet(
        tuple(
            deployment.operational_replica(
                capacity=per_replica_capacity,
                timeout_s=timeout_s,
            )
            for deployment in deployments
        )
    )
    runtime_binding_digest = canonical_digest({
        "lane": "platform-substitute",
        "model_identity_digest": deployments[0].model_identity_digest,
        "replica_set_digest": replicas.replica_set_digest,
        "method_program_digest": SELF_CONSISTENCY_GSM8K_METHOD_PROGRAM.program_digest,
        "model_request_schema": "model-request.v1",
        "sampling": {
            "reasoning_path_count": SELF_CONSISTENCY_GSM8K_FIDELITY.reasoning_path_count,
            "temperature": SELF_CONSISTENCY_GSM8K_FIDELITY.temperature,
            "top_k": SELF_CONSISTENCY_GSM8K_FIDELITY.top_k,
            "base_seed": base_seed,
            "task_seed_stride": 1000,
        },
    })

    output_root.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "schema": "noetrium.experiment-manifest.v2",
        "experiment_id": "self-consistency-gsm8k-qwen3-8b-substitute",
        "lane": "platform-substitute",
        "matched_reproduction": False,
        "claim_ready": False,
        "claim_blockers": (
            "paper_reference_model_mismatch",
            "operational_endpoints_not_qualified",
        ),
        "paper_reference_model": SELF_CONSISTENCY_GSM8K_FIDELITY.paper_reference_model,
        "paper_reported_reference_accuracy_percent": (
            SELF_CONSISTENCY_GSM8K_FIDELITY.paper_gsm8k_self_consistency_percent
        ),
        "source_sha": source_sha,
        "method_id": "self-consistency",
        "method_program_digest": SELF_CONSISTENCY_GSM8K_METHOD_PROGRAM.program_digest,
        "prompt_bundle_id": COT_GSM8K_PROMPT_BUNDLE_ID,
        "prompt_digest": COT_GSM8K_PROMPT_DIGEST,
        "benchmark_id": "gsm8k",
        "benchmark_revision": materialized.cut.revision_id,
        "benchmark_file_sha256": materialized.file_sha256,
        "benchmark_git_blob_sha1": materialized.git_blob_sha1,
        "model_identity_digest": deployments[0].model_identity_digest,
        "model": asdict(model),
        "replica_set_digest": replicas.replica_set_digest,
        "deployments": tuple({
            "deployment_id": row.deployment_id,
            "deployment_generation": row.deployment_generation,
            "endpoint_base_url": row.endpoint_base_url,
            "identity_document_digest": row.identity_document_digest,
            "served_model_name": row.served_model_name,
        } for row in deployments),
        "sampling": {
            "reasoning_path_count": SELF_CONSISTENCY_GSM8K_FIDELITY.reasoning_path_count,
            "temperature": SELF_CONSISTENCY_GSM8K_FIDELITY.temperature,
            "top_k": SELF_CONSISTENCY_GSM8K_FIDELITY.top_k,
            "max_tokens": max_tokens,
            "base_seed": base_seed,
            "task_seed_stride": 1000,
            "disable_thinking": disable_thinking,
            "served_model_name": served_model_name,
        },
        "task_start": start,
        "task_count": count,
        "task_concurrency": task_concurrency,
        "per_replica_capacity": per_replica_capacity,
        "environment_kind": "text_world",
        "runtime_binding_digest": runtime_binding_digest,
        "model_request_schema": "model-request.v1",
    }
    manifest["manifest_digest"] = canonical_digest(manifest)
    (output_root / "experiment-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    concurrency = build_concurrency_runtime()
    group = concurrency.open_task_group(
        f"self-consistency-gsm8k:{str(manifest['manifest_digest'])[:16]}"
    )
    admission_registry = ModelAdmissionRegistry()
    pool = build_adaptive_operational_endpoint_pool(
        replicas,
        task_group=group,
        admission_registry=admission_registry,
    )
    rows: list[dict[str, object]] = []
    started = time.time()
    try:
        with ThreadPoolExecutor(max_workers=min(task_concurrency, count)) as executor:
            futures = {
                executor.submit(
                    _run_substitute_task,
                    task,
                    endpoint_pool=pool,
                    model=model,
                    served_model_name=served_model_name,
                    output_root=output_root,
                    runtime_binding_digest=runtime_binding_digest,
                    max_tokens=max_tokens,
                    base_seed=base_seed,
                    timeout_s=timeout_s,
                    disable_thinking=disable_thinking,
                ): task.record.task_id
                for task in selected
            }
            for future in as_completed(futures):
                row = future.result()
                rows.append(row)
                with (output_root / "trajectories.jsonl").open(
                    "a", encoding="utf-8"
                ) as handle:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
        snapshot = pool.snapshot()
    finally:
        admission_registry.close()
        concurrency.close()

    rows.sort(key=lambda row: str(row["task_id"]))
    completed = [row for row in rows if row["status"] == "succeeded"]
    correct = sum(bool(row["correct"]) for row in completed)
    pool_snapshot = asdict(snapshot)
    (output_root / "pool-snapshot.json").write_text(
        json.dumps(pool_snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary: dict[str, object] = {
        "schema": "noetrium.experiment-result-summary.v2",
        "experiment_manifest_digest": manifest["manifest_digest"],
        "lane": "platform-substitute",
        "matched_reproduction": False,
        "claim_ready": False,
        "paper_reported_reference_accuracy_percent": (
            SELF_CONSISTENCY_GSM8K_FIDELITY.paper_gsm8k_self_consistency_percent
        ),
        "task_count_requested": count,
        "task_count_succeeded": len(completed),
        "task_count_failed": len(rows) - len(completed),
        "correct_count": correct,
        "measured_accuracy_percent": (
            100.0 * correct / len(completed) if completed else None
        ),
        "evidence_complete_count": sum(
            row["evidence_status"] == MethodEvidenceStatus.COMPLETE.value
            for row in rows
        ),
        "model_call_count": sum(
            int(row["model_call_count"])
            for row in completed
            if row["model_call_count"] is not None
        ),
        "model_request_record_count": sum(
            int(row["model_request_record_count"])
            for row in completed
            if row["model_request_record_count"] is not None
        ),
        "replica_set_digest": replicas.replica_set_digest,
        "pool_snapshot": pool_snapshot,
        "total_duration_seconds": time.time() - started,
        "failure_classes": {
            name: sum(row["failure_class"] == name for row in rows)
            for name in sorted({
                str(row["failure_class"])
                for row in rows
                if row["failure_class"] is not None
            })
        },
    }
    summary["result_digest"] = canonical_digest(summary)
    (output_root / "result-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if len(completed) != count:
        raise RuntimeError(
            f"Self-Consistency substitute run failed closed: {len(completed)}/{count} tasks succeeded"
        )
    expected_calls = count * SELF_CONSISTENCY_GSM8K_FIDELITY.reasoning_path_count
    if summary["model_call_count"] != expected_calls:
        raise RuntimeError("Self-Consistency model-call cardinality drift")
    if summary["model_request_record_count"] != expected_calls:
        raise RuntimeError("Self-Consistency durable model-request cardinality drift")
    print(json.dumps(summary, sort_keys=True))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument(
        "--model-identity",
        type=Path,
        action="append",
        required=True,
        dest="model_identities",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--base-seed", type=int, default=0)
    parser.add_argument("--per-replica-capacity", type=int, default=1)
    parser.add_argument("--task-concurrency", type=int, default=4)
    parser.add_argument("--timeout-s", type=float, default=180.0)
    parser.add_argument("--enable-thinking", action="store_true")
    args = parser.parse_args()
    run_external_qwen_substitute_pool(
        benchmark_path=args.benchmark,
        model_identity_paths=tuple(args.model_identities),
        output_root=args.output_root,
        source_sha=args.source_sha,
        start=args.start,
        count=args.count,
        max_tokens=args.max_tokens,
        base_seed=args.base_seed,
        per_replica_capacity=args.per_replica_capacity,
        task_concurrency=args.task_concurrency,
        timeout_s=args.timeout_s,
        disable_thinking=not args.enable_thinking,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PooledSelfConsistencyReasoner",
    "SelfConsistencyGSM8KEpisodeResult",
    "SelfConsistencyGSM8KModelBinding",
    "SelfConsistencyInvocation",
    "run_external_qwen_substitute_pool",
    "run_self_consistency_gsm8k_episode",
]
