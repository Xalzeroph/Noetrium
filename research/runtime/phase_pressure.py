from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib
import json
from pathlib import Path
import subprocess
from threading import Lock
import time

from noetrium_platform.capabilities.model.request.composition import (
    build_directory_model_request_recorder,
)
from noetrium_platform.capabilities.model.serving.endpoint import (
    ModelEndpointRoute,
    OperationalModelEndpointReplica,
    OperationalModelEndpointReplicaSet,
    OperationalModelServingInventory,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    PinnedReplicaSelectionPolicy,
)
from noetrium_platform.capabilities.model.serving.endpoint.composition import (
    build_adaptive_operational_endpoint_pool,
)
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionRegistry
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    ImmutableModelIdentity,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import MethodNodeKind, MethodProgram
from noetrium_platform.research.execution.workflow.composition import (
    DispatchPoolBackedMethodAgentLoop,
    MethodAgentLoopRouter,
    MethodModelEndpointBinding,
    MethodRuntimePortInventory,
    StructuredViewChatRequestFactory,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from noetrium_platform.research.experimentation.experiment.api import ExperimentTaskSpec
from noetrium_platform.research.experimentation.workload.composition import (
    DeclarativeWorkloadMethodCompiler,
    compose_method_runtime_bindings,
)

ROOT = Path(__file__).resolve().parents[2]
REPRO_ROOT = ROOT / "research" / "reproductions"
_PRINT_LOCK = Lock()


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path}: expected object")
    return value


def _git_sha() -> str:
    return subprocess.check_output(
        [
            "git",
            "-c",
            f"safe.directory={ROOT}",
            "rev-parse",
            "HEAD",
        ],
        cwd=ROOT,
        text=True,
    ).strip()


def _model(document: dict) -> ImmutableModelIdentity:
    value = document.get("model")
    if not isinstance(value, dict):
        raise ValueError("operational inventory lacks model identity")
    return ImmutableModelIdentity(**value)


def load_operational_inventory(path: Path) -> OperationalModelServingInventory:
    document = _json(path)
    schema = document.get("schema")
    if schema != "noetrium.operational-model-serving-inventory.v1":
        raise ValueError(
            "operational inventory schema mismatch: "
            f"expected 'noetrium.operational-model-serving-inventory.v1', got {schema!r}"
        )
    served_model_name = document.get("served_model_name")
    if not isinstance(served_model_name, str) or not served_model_name.strip():
        raise ValueError("operational inventory requires served_model_name")
    rows = document.get("replicas")
    if not isinstance(rows, list) or not rows:
        raise ValueError("operational inventory requires non-empty replicas")
    replicas: list[OperationalModelEndpointReplica] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise TypeError(f"operational inventory replica[{index}] must be object")
        route = ModelEndpointRoute(
            deployment_id=str(row["deployment_id"]),
            deployment_generation=str(row["deployment_generation"]),
            base_url=str(row["base_url"]),
            completion_path=str(row.get("completion_path", "/v1/chat/completions")),
            timeout_s=float(row.get("timeout_s", 120.0)),
        )
        capacity = row.get("capacity")
        if type(capacity) is not int or capacity <= 0:
            raise ValueError(f"operational inventory replica[{index}] capacity must be positive")
        replicas.append(OperationalModelEndpointReplica(route, capacity))
    return OperationalModelServingInventory(
        model=_model(document),
        served_model_name=served_model_name,
        replica_set=OperationalModelEndpointReplicaSet(tuple(replicas)),
    )


def _program_for(package: str) -> MethodProgram | None:
    module = importlib.import_module(f"research.reproductions.{package}.program")
    programs = [
        value
        for value in vars(module).values()
        if isinstance(value, MethodProgram)
        and value.configuration.get("authoring_form") == "agent_phase_sequence.v1"
    ]
    unique = {value.program_digest: value for value in programs}
    if len(unique) != 1:
        return None
    return next(iter(unique.values()))


def discover() -> tuple[tuple[str, MethodProgram], ...]:
    rows: list[tuple[str, MethodProgram]] = []
    for root in sorted(path for path in REPRO_ROOT.iterdir() if path.is_dir()):
        if not (root / "program.py").is_file():
            continue
        try:
            program = _program_for(root.name)
        except Exception:
            continue
        if program is not None:
            rows.append((root.name, program))
    return tuple(rows)


def _agent_ids(program: MethodProgram) -> tuple[str, ...]:
    ids: set[str] = set()
    for node in program.graph.nodes:
        if node.kind is not MethodNodeKind.AGENT:
            continue
        if node.agent_id is not None:
            ids.add(node.agent_id)
        ids.update(node.agent_targets)
    if not ids:
        raise ValueError("phase pressure program has no agent nodes")
    return tuple(sorted(ids))


def _objective(package: str, program: MethodProgram) -> str:
    config = dict(program.configuration)
    protocol = config.get("protocol")
    if isinstance(protocol, (tuple, list)) and protocol:
        return "Platform pressure execution of the declared method protocol: " + "; ".join(
            str(x) for x in protocol[:4]
        )
    return (
        f"Execute the declared {package} method phases faithfully on this pressure task. "
        "Return phase outputs that are internally consistent with the method instructions."
    )


def _run_episode(
    *,
    package: str,
    program: MethodProgram,
    repetition: int,
    output_root: Path,
    source_sha: str,
    inventory: OperationalModelServingInventory,
    pool,
    args: argparse.Namespace,
) -> dict:
    output = output_root / package / f"rep-{repetition:02d}"
    output.mkdir(parents=True, exist_ok=True)
    factory = StructuredViewChatRequestFactory(
        inventory.served_model_name,
        {
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        system_instruction=(
            "This is a platform pressure lane, not a matched paper reproduction. "
            "Follow the current Method phase instruction exactly and do not invent "
            "external environment observations."
        ),
    )
    recorder = build_directory_model_request_recorder(output / "model-requests")
    loops = {}
    prompt_bindings = {}
    for agent_id in _agent_ids(program):
        prompt_digest = canonical_digest({
            "lane": "platform-pressure",
            "program_digest": program.program_digest,
            "agent_id": agent_id,
            "request_factory_digest": factory.digest,
        })
        binding = MethodModelEndpointBinding(
            agent_id=agent_id,
            role=agent_id,
            model=inventory.model,
            prompt_generation_id=f"platform-pressure:{package}:{agent_id}:v1",
            prompt_id=f"platform-pressure:{package}:{agent_id}",
            prompt_digest=prompt_digest,
            request_factory_digest=factory.digest,
        )
        loops[agent_id] = DispatchPoolBackedMethodAgentLoop(
            binding=binding,
            pool=pool,
            recorder=recorder,
            request_factory=factory,
        )
        prompt_bindings[agent_id] = binding.digest
    router = MethodAgentLoopRouter(loops)
    task = ExperimentTaskSpec(
        task_id=f"pressure:{package}:{repetition}",
        family="platform-phase-pressure",
        objective=_objective(package, program),
        context=(
            "Synthetic execution-pressure task. No benchmark score or paper claim "
            "may be derived from this lane."
        ),
        max_steps=max(args.max_method_steps, len(program.graph.nodes) + 2),
        max_seconds=args.timeout_s,
    )
    runtime = compose_method_runtime_bindings(
        program,
        MethodRuntimePortInventory(agent_loop=router),
        state_root=output / "state",
    )
    compiler = DeclarativeWorkloadMethodCompiler(program=program, runtime=runtime)
    invocation = compiler.compile(
        task,
        ExecutionContext(
            f"phase-pressure:{package}:rep-{repetition}",
            f"trace:{source_sha[:16]}",
            "root",
            study_id="platform-phase-pressure",
            condition_id="operational-substitute",
            platform_generation=source_sha,
        ),
    )
    started = time.time()
    result = UniversalMethodMachine(max_steps=task.max_steps).run(
        invocation.program,
        runtime=invocation.runtime,
        input_value=invocation.input_value,
        initial_state=invocation.initial_state,
        resume=invocation.resume,
    )
    record = {
        "schema": "noetrium.phase-pressure-result.v2",
        "lane": "platform-pressure",
        "matched_reproduction": False,
        "claim_ready": False,
        "package": package,
        "repetition": repetition,
        "source_sha": source_sha,
        "program_digest": program.program_digest,
        "compiler_digest": compiler.digest,
        "runtime_binding_digest": invocation.runtime.effective_runtime_binding_digest,
        "agent_router_digest": router.identity_digest,
        "prompt_binding_digests": prompt_bindings,
        "model_identity_digest": canonical_digest(inventory.model),
        "serving_inventory_digest": inventory.identity_digest,
        "replica_set_digest": inventory.replica_set.replica_set_digest,
        "status": result.status.value,
        "evidence_status": result.evidence_status.value,
        "run_digest": result.run_digest,
        "step_count": result.step_count,
        "effect_receipt_count": len(result.effect_receipts),
        "event_count": len(result.events),
        "duration_seconds": time.time() - started,
        "failure": result.failure,
        "failure_code": result.failure_code,
        "failure_phase": result.failure_phase,
    }
    record["record_digest"] = canonical_digest(record)
    (output / "result.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with _PRINT_LOCK:
        print(
            "RESULT",
            package,
            repetition,
            result.status.value,
            result.evidence_status.value,
            result.step_count,
            flush=True,
        )
    return record


def _failed_record(
    *,
    package: str,
    repetition: int,
    output_root: Path,
    source_sha: str,
    inventory: OperationalModelServingInventory,
    exc: BaseException,
) -> dict:
    output = output_root / package / f"rep-{repetition:02d}"
    output.mkdir(parents=True, exist_ok=True)
    record = {
        "schema": "noetrium.phase-pressure-result.v2",
        "lane": "platform-pressure",
        "matched_reproduction": False,
        "claim_ready": False,
        "package": package,
        "repetition": repetition,
        "source_sha": source_sha,
        "model_identity_digest": canonical_digest(inventory.model),
        "serving_inventory_digest": inventory.identity_digest,
        "replica_set_digest": inventory.replica_set.replica_set_digest,
        "status": "failed",
        "evidence_status": "unknown",
        "failure": f"{type(exc).__name__}: {exc}",
        "failure_code": "pressure_lane_exception",
        "failure_phase": "execution",
    }
    record["record_digest"] = canonical_digest(record)
    (output / "result.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with _PRINT_LOCK:
        print("FAILED", package, repetition, record["failure"], flush=True)
    return record


def run(args: argparse.Namespace) -> dict:
    inventory = load_operational_inventory(args.deployment_inventory)
    source_sha = _git_sha()
    all_rows = discover()
    selected = tuple(
        row for index, row in enumerate(all_rows)
        if index % args.shard_count == args.shard_index
    )
    if args.limit is not None:
        selected = selected[: args.limit]
    jobs = tuple(
        (package, program, args.repetition_offset + local_repetition)
        for package, program in selected
        for local_repetition in range(args.repetitions)
    )
    if not jobs:
        raise RuntimeError("phase pressure selection produced no jobs")

    auto_workers = min(len(jobs), inventory.capacity)
    worker_count = auto_workers if args.worker_count is None else args.worker_count
    if worker_count < 1:
        raise ValueError("worker_count must be positive")
    if worker_count > inventory.capacity:
        raise ValueError(
            "worker_count exceeds frozen operational inventory capacity: "
            f"workers={worker_count} capacity={inventory.capacity}"
        )

    args.output_root.mkdir(parents=True, exist_ok=True)
    concurrency = build_concurrency_runtime()
    group = concurrency.open_task_group(
        "phase-pressure:model-endpoints:"
        + canonical_digest({
            "inventory": inventory.identity_digest,
            "source_sha": source_sha,
        })[:16]
    )
    admission = ModelAdmissionRegistry()
    selection_policy = (
        None
        if args.deployment_id is None
        else PinnedReplicaSelectionPolicy(args.deployment_id)
    )
    pool = build_adaptive_operational_endpoint_pool(
        inventory.replica_set,
        task_group=group,
        admission_registry=admission,
        selection_policy=selection_policy,
    )

    records: list[dict] = []
    try:
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="phase-pressure",
        ) as executor:
            futures = {
                executor.submit(
                    _run_episode,
                    package=package,
                    program=program,
                    repetition=repetition,
                    output_root=args.output_root,
                    source_sha=source_sha,
                    inventory=inventory,
                    pool=pool,
                    args=args,
                ): (package, repetition)
                for package, program, repetition in jobs
            }
            for future in as_completed(futures):
                package, repetition = futures[future]
                try:
                    records.append(future.result())
                except BaseException as exc:
                    records.append(_failed_record(
                        package=package,
                        repetition=repetition,
                        output_root=args.output_root,
                        source_sha=source_sha,
                        inventory=inventory,
                        exc=exc,
                    ))
    finally:
        snapshot = pool.snapshot()
        admission.close()
        group.close(cancel_pending=True)
        concurrency.close()

    records.sort(key=lambda row: (str(row["package"]), int(row["repetition"])))
    summary = {
        "schema": "noetrium.phase-pressure-summary.v2",
        "lane": "platform-pressure",
        "matched_reproduction": False,
        "claim_ready": False,
        "source_sha": source_sha,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "repetition_offset": args.repetition_offset,
        "repetitions": args.repetitions,
        "package_count": len(selected),
        "run_count": len(records),
        "worker_count": worker_count,
        "auto_worker_count": auto_workers,
        "serving_inventory_digest": inventory.identity_digest,
        "replica_set_digest": inventory.replica_set.replica_set_digest,
        "selection_policy_digest": snapshot.selection_policy_digest,
        "replica_snapshot": [
            {
                "deployment_id": row.deployment_id,
                "capacity": row.capacity,
                "completed": row.completed,
                "failures": row.failures,
                "selections": row.selections,
                "ewma_latency_seconds": row.ewma_latency_seconds,
                "cooling_down": row.cooling_down,
            }
            for row in snapshot.replicas
        ],
        "succeeded": sum(row["status"] == "succeeded" for row in records),
        "evidence_complete": sum(row.get("evidence_status") == "complete" for row in records),
        "failed": sum(row["status"] != "succeeded" for row in records),
        "packages": tuple(package for package, _ in selected),
    }
    summary["summary_digest"] = canonical_digest(summary)
    (args.output_root / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("SUMMARY", json.dumps(summary, sort_keys=True), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployment-inventory", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--repetition-offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--worker-count", type=int)
    parser.add_argument("--deployment-id")
    parser.add_argument("--max-tokens", type=int, default=384)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout-s", type=float, default=180.0)
    parser.add_argument("--max-method-steps", type=int, default=128)
    args = parser.parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        raise ValueError("invalid shard index/count")
    if args.repetitions < 1:
        raise ValueError("repetitions must be positive")
    if args.repetition_offset < 0:
        raise ValueError("repetition_offset must be non-negative")
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
