from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import subprocess
import time

from noetrium_platform.capabilities.model.request.composition import build_directory_model_request_recorder
from noetrium_platform.capabilities.model.serving.endpoint import ModelEndpointRoute
from noetrium_platform.capabilities.model.serving.endpoint.providers import AsyncioJsonTransport, OpenAICompatibleModelEndpoint
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionController
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity, canonical_digest
from noetrium_platform.research.execution.workflow.api import MethodNodeKind, MethodProgram
from noetrium_platform.research.execution.workflow.composition import (
    EndpointBackedMethodAgentLoop,
    MethodAgentLoopRouter,
    MethodModelEndpointBinding,
    StructuredViewChatRequestFactory,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from noetrium_platform.research.experimentation.experiment.api import ExperimentTaskSpec
from noetrium_platform.research.experimentation.workload.composition import (
    DeclarativeWorkloadMethodCompiler,
    MethodRuntimeBindings,
)

ROOT = Path(__file__).resolve().parents[2]
REPRO_ROOT = ROOT / "research" / "reproductions"


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path}: expected object")
    return value


def _git_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def _model(document: dict) -> ImmutableModelIdentity:
    value = document.get("model")
    if not isinstance(value, dict):
        raise ValueError("model manifest lacks model identity")
    return ImmutableModelIdentity(**value)


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


def run(args: argparse.Namespace) -> dict:
    manifest = _json(args.model_manifest)
    model = _model(manifest)
    endpoint_url = str(manifest["endpoint_base_url"])
    deployment_id = str(manifest["deployment_id"])
    deployment_generation = str(manifest["deployment_generation"])
    source_sha = _git_sha()

    all_rows = discover()
    selected = tuple(
        row for index, row in enumerate(all_rows)
        if index % args.shard_count == args.shard_index
    )
    if args.limit is not None:
        selected = selected[: args.limit]

    args.output_root.mkdir(parents=True, exist_ok=True)
    concurrency = build_concurrency_runtime()
    group = concurrency.open_task_group(
        f"phase-pressure:{args.shard_index}:{canonical_digest(tuple(x[0] for x in selected))[:12]}"
    )
    endpoint = OpenAICompatibleModelEndpoint(
        route=ModelEndpointRoute(
            deployment_id,
            deployment_generation,
            endpoint_url,
            timeout_s=args.timeout_s,
        ),
        transport=AsyncioJsonTransport(),
        task_group=group,
        admission=ModelAdmissionController(args.admission_limit),
    )

    records: list[dict] = []
    try:
        for package, program in selected:
            for repetition in range(args.repetitions):
                output = args.output_root / package / f"rep-{repetition:02d}"
                output.mkdir(parents=True, exist_ok=True)
                factory = StructuredViewChatRequestFactory(
                    "qwen",
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
                        model=model,
                        prompt_generation_id=(
                            f"platform-pressure:{package}:{agent_id}:v1"
                        ),
                        prompt_id=f"platform-pressure:{package}:{agent_id}",
                        prompt_digest=prompt_digest,
                        request_factory_digest=factory.digest,
                    )
                    loops[agent_id] = EndpointBackedMethodAgentLoop(
                        binding=binding,
                        endpoint=endpoint,
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
                compiler = DeclarativeWorkloadMethodCompiler(
                    program=program,
                    runtime=MethodRuntimeBindings(
                        agent_loop=router,
                        state_root=output / "state",
                    ),
                )
                invocation = compiler.compile(
                    task,
                    ExecutionContext(
                        f"phase-pressure:{package}:rep-{repetition}",
                        f"trace:{source_sha[:16]}:{args.shard_index}",
                        "root",
                        study_id="platform-phase-pressure",
                        condition_id="qwen3-8b-substitute",
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
                    "schema": "noetrium.phase-pressure-result.v1",
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
                    "model_identity_digest": canonical_digest(model),
                    "deployment_id": deployment_id,
                    "deployment_generation": deployment_generation,
                    "endpoint_base_url": endpoint_url,
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
                records.append(record)
                print(
                    "RESULT",
                    package,
                    repetition,
                    result.status.value,
                    result.evidence_status.value,
                    result.step_count,
                    flush=True,
                )
    finally:
        group.close(cancel_pending=True)

    summary = {
        "schema": "noetrium.phase-pressure-summary.v1",
        "lane": "platform-pressure",
        "matched_reproduction": False,
        "claim_ready": False,
        "source_sha": source_sha,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "package_count": len(selected),
        "run_count": len(records),
        "succeeded": sum(row["status"] == "succeeded" for row in records),
        "evidence_complete": sum(row["evidence_status"] == "complete" for row in records),
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
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-tokens", type=int, default=384)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--admission-limit", type=int, default=4)
    parser.add_argument("--timeout-s", type=float, default=180.0)
    parser.add_argument("--max-method-steps", type=int, default=128)
    args = parser.parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        raise ValueError("invalid shard index/count")
    if args.repetitions < 1:
        raise ValueError("repetitions must be positive")
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
