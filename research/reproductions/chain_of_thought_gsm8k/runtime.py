from __future__ import annotations
from noetrium_platform.composition.method_runtime import bind_standard_method_runtime

from collections.abc import Mapping
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import time

from noetrium_platform.composition.model_requests import (
    build_directory_model_request_recorder,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    AsyncioJsonTransport,
    OpenAICompatibleModelEndpoint,
    load_operational_model_serving_inventory,
)
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionController
from noetrium_platform.foundation.kernel.concurrency.composition import (
    build_concurrency_runtime,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_bytes,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodEvidenceStatus,
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.composition import (
    EndpointBackedMethodAgentLoop,
    MethodModelEndpointBinding,
    PromptViewChatRequestFactory,
)
from noetrium_platform.research.execution.workflow.providers import (
    DirectoryEventMethodEvidence,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine

from research.benchmarks.gsm8k import (
    materialize_archived_gsm8k_test,
    verify_gsm8k_completion,
)
from .program import (
    CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM,
    chain_of_thought_gsm8k_initial_state,
)
from .prompt import (
    COT_GSM8K_PROMPT_BUNDLE_ID,
    COT_GSM8K_PROMPT_DIGEST,
)


_SHA40 = re.compile(r"[0-9a-f]{40}\Z")


def _require_source_sha(value: str) -> str:
    if _SHA40.fullmatch(value) is None:
        raise ValueError("experiment source SHA must be lowercase Git SHA-1")
    return value


def _effect(receipt) -> dict:
    value = asdict(receipt)
    value["effect_class"] = receipt.effect_class.value
    value["certainty"] = receipt.certainty.value
    return value


def _jsonable(value):
    return json.loads(canonical_bytes(value))


def _event(event) -> dict:
    return {"kind": event.kind, "payload": _jsonable(event.payload)}


def run_external_qwen_substitute(
    *,
    benchmark_path: Path,
    deployment_inventory_path: Path,
    output_root: Path,
    source_sha: str,
    start: int,
    count: int,
    max_tokens: int,
    admission_limit: int,
    disable_thinking: bool,
    deployment_id: str | None = None,
) -> dict:
    """Run a clearly-labelled substitute lane; never claims matched PaLM reproduction."""

    source_sha = _require_source_sha(source_sha)
    if start < 0 or count <= 0:
        raise ValueError("task start/count must be positive bounds")
    if max_tokens <= 0 or admission_limit <= 0:
        raise ValueError("max_tokens/admission_limit must be positive")

    materialized = materialize_archived_gsm8k_test(benchmark_path)
    selected = materialized.tasks[start : start + count]
    if len(selected) != count:
        raise ValueError("requested task range exceeds GSM8K test cut")

    inventory = load_operational_model_serving_inventory(deployment_inventory_path)
    model = inventory.model
    replicas = inventory.replica_set.replicas
    if deployment_id is None:
        replica = replicas[0]
    else:
        matches = tuple(row for row in replicas if row.deployment_id == deployment_id)
        if len(matches) != 1:
            raise ValueError(
                f"CoT deployment_id is not present exactly once in inventory: {deployment_id}"
            )
        replica = matches[0]
    deployment_id = replica.deployment_id
    deployment_generation = replica.deployment_generation
    endpoint_base_url = replica.route.base_url
    model_identity_digest = canonical_digest(model)
    serving_inventory_digest = inventory.identity_digest
    replica_set_digest = inventory.replica_set.replica_set_digest
    served_model_name = inventory.served_model_name

    generation_options: dict[str, object] = {
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if disable_thinking:
        generation_options["chat_template_kwargs"] = {"enable_thinking": False}
    request_factory = PromptViewChatRequestFactory(served_model_name, generation_options)
    binding = MethodModelEndpointBinding(
        agent_id="cot.reasoner",
        role="reasoner",
        model=model,
        prompt_generation_id=COT_GSM8K_PROMPT_BUNDLE_ID,
        prompt_id=COT_GSM8K_PROMPT_BUNDLE_ID,
        prompt_digest=COT_GSM8K_PROMPT_DIGEST,
        request_factory_digest=request_factory.digest,
    )
    runtime_binding_digest = canonical_digest(
        {
            "lane": "platform-substitute",
            "model_identity_digest": model_identity_digest,
            "serving_inventory_digest": serving_inventory_digest,
            "replica_set_digest": replica_set_digest,
            "deployment_generation": deployment_generation,
            "request_factory_digest": request_factory.digest,
            "method_program_digest": CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM.program_digest,
        }
    )

    output_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "noetrium.experiment-manifest.v2",
        "experiment_id": "cot-gsm8k-qwen3-8b-substitute",
        "lane": "platform-substitute",
        "matched_reproduction": False,
        "paper_reference_model": "PaLM-540B",
        "paper_reported_reference_accuracy_percent": 56.9,
        "source_sha": source_sha,
        "method_id": "chain-of-thought",
        "method_program_digest": CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM.program_digest,
        "prompt_bundle_id": COT_GSM8K_PROMPT_BUNDLE_ID,
        "prompt_digest": COT_GSM8K_PROMPT_DIGEST,
        "benchmark_id": "gsm8k",
        "benchmark_revision": materialized.cut.revision_id,
        "benchmark_file_sha256": materialized.file_sha256,
        "benchmark_git_blob_sha1": materialized.git_blob_sha1,
        "model_identity_digest": model_identity_digest,
        "serving_inventory_digest": serving_inventory_digest,
        "replica_set_digest": replica_set_digest,
        "model": asdict(model),
        "deployment_id": deployment_id,
        "deployment_generation": deployment_generation,
        "endpoint_base_url": endpoint_base_url,
        "decoding": generation_options,
        "task_start": start,
        "task_count": count,
        "seed": None,
        "environment_kind": "text_world",
        "runtime_binding_digest": runtime_binding_digest,
    }
    manifest["manifest_digest"] = canonical_digest(manifest)
    (output_root / "experiment-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    concurrency = build_concurrency_runtime()
    group = concurrency.open_task_group(
        f"cot-gsm8k-qwen3-8b:{manifest['manifest_digest'][:16]}"
    )
    endpoint = OpenAICompatibleModelEndpoint(
        route=replica.route,
        transport=AsyncioJsonTransport(),
        task_group=group,
        admission=ModelAdmissionController(admission_limit),
    )
    recorder = build_directory_model_request_recorder(output_root / "model-requests")
    agent_loop = EndpointBackedMethodAgentLoop(
        binding=binding,
        endpoint=endpoint,
        recorder=recorder,
        request_factory=request_factory,
    )

    trajectories: list[dict] = []
    started = time.time()
    try:
        for task in selected:
            task_id = task.record.task_id
            run_id = f"cot-gsm8k-qwen3-8b-substitute:{task_id}"
            task_root = output_root / "tasks" / task_id.replace(":", "_")
            evidence = DirectoryEventMethodEvidence(task_root / "evidence")
            runtime = MethodRuntimeContext(
                execution=ExecutionContext(
                    run_id,
                    f"trace:{manifest['manifest_digest'][:24]}",
                    "root",
                    study_id="cot-gsm8k-qwen3-8b-substitute",
                    condition_id="cot-8shot-qwen3-8b",
                    task_id=task_id,
                    platform_generation=source_sha,
                ),
                agent_loop=agent_loop,
                evidence=evidence,
                binding_plan_digest=binding.digest,
                runtime_binding_digest=runtime_binding_digest,
            )
            runtime = bind_standard_method_runtime(
                CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM,
                runtime,
                state_root=task_root / "machine",
            )
            task_started = time.time()
            try:
                result = UniversalMethodMachine(max_steps=8).run(
                    CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM,
                    runtime=runtime,
                    initial_state=chain_of_thought_gsm8k_initial_state(
                        task_id=task_id,
                        question=task.question,
                    ),
                )
                completion = (
                    result.value.get("completion")
                    if isinstance(result.value, Mapping)
                    else None
                )
                if not isinstance(completion, str):
                    raise RuntimeError("CoT Method result has no completion")
                correct, predicted = verify_gsm8k_completion(
                    completion,
                    task.final_answer,
                )
                invocations = [
                    _jsonable(event.payload)
                    for event in result.events
                    if event.kind == "model.invocation"
                ]
                row = {
                    "task_id": task_id,
                    "run_id": run_id,
                    "status": result.status.value,
                    "evidence_status": result.evidence_status.value,
                    "run_digest": result.run_digest,
                    "question_digest": task.record.question_digest,
                    "answer_digest": task.record.answer_digest,
                    "content_digest": task.record.content_digest,
                    "gold_final_answer": task.final_answer,
                    "predicted_final_answer": predicted,
                    "correct": correct,
                    "completion": completion,
                    "model_invocations": invocations,
                    "effect_receipts": tuple(_effect(item) for item in result.effect_receipts),
                    "events": tuple(_event(item) for item in result.events),
                    "duration_seconds": time.time() - task_started,
                    "failure_class": None,
                    "failure": result.failure,
                }
                if result.status is not MethodRunStatus.SUCCEEDED:
                    row["failure_class"] = "method-runtime"
                if result.evidence_status is not MethodEvidenceStatus.COMPLETE:
                    row["failure_class"] = row["failure_class"] or "evidence"
            except Exception as exc:
                row = {
                    "task_id": task_id,
                    "run_id": run_id,
                    "status": "failed",
                    "evidence_status": "incomplete",
                    "question_digest": task.record.question_digest,
                    "answer_digest": task.record.answer_digest,
                    "content_digest": task.record.content_digest,
                    "gold_final_answer": task.final_answer,
                    "predicted_final_answer": None,
                    "correct": False,
                    "completion": None,
                    "model_invocations": (),
                    "effect_receipts": (),
                    "events": (),
                    "duration_seconds": time.time() - task_started,
                    "failure_class": "model-or-runtime",
                    "failure": f"{type(exc).__qualname__}: {exc}",
                }
                trajectories.append(row)
                with (output_root / "trajectories.jsonl").open(
                    "a", encoding="utf-8"
                ) as handle:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
                raise
            trajectories.append(row)
            with (output_root / "trajectories.jsonl").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
            if row["failure_class"] is not None:
                raise RuntimeError(
                    f"CoT task failed closed: {task_id}: "
                    f"{row['failure_class']}: {row['failure']}"
                )
    finally:
        concurrency.close()

    completed = [row for row in trajectories if row["status"] == "succeeded"]
    correct = sum(bool(row["correct"]) for row in completed)
    summary = {
        "schema": "noetrium.experiment-result-summary.v1",
        "experiment_manifest_digest": manifest["manifest_digest"],
        "lane": "platform-substitute",
        "matched_reproduction": False,
        "paper_reported_reference_accuracy_percent": 56.9,
        "task_count_requested": count,
        "task_count_succeeded": len(completed),
        "task_count_failed": len(trajectories) - len(completed),
        "correct_count": correct,
        "measured_accuracy_percent": (
            100.0 * correct / len(completed) if completed else None
        ),
        "evidence_complete_count": sum(
            row["evidence_status"] == MethodEvidenceStatus.COMPLETE.value
            for row in trajectories
        ),
        "total_duration_seconds": time.time() - started,
        "failure_classes": {
            name: sum(row["failure_class"] == name for row in trajectories)
            for name in sorted(
                {row["failure_class"] for row in trajectories if row["failure_class"]}
            )
        },
    }
    summary["result_digest"] = canonical_digest(summary)
    (output_root / "result-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--deployment-inventory", type=Path, required=True)
    parser.add_argument("--deployment-id")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--admission-limit", type=int, default=4)
    parser.add_argument("--enable-thinking", action="store_true")
    args = parser.parse_args()
    run_external_qwen_substitute(
        benchmark_path=args.benchmark,
        deployment_inventory_path=args.deployment_inventory,
        output_root=args.output_root,
        source_sha=args.source_sha,
        start=args.start,
        count=args.count,
        max_tokens=args.max_tokens,
        admission_limit=args.admission_limit,
        disable_thinking=not args.enable_thinking,
        deployment_id=args.deployment_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
