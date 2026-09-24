from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium import api
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.reproductions import build_research
from research.reproductions.contracts import ReproductionAssetKind
from research.reproductions.fleet import (
    ReproductionFleetExecutionAuthorities,
    run_repository_execution_fleet,
)
from research.reproductions.research_os import (
    compile_reproduction_research_program,
    discover_reproduction_definitions,
    executable_reproduction_definitions,
    is_research_os_executable,
    resolve_benchmark_split_consumers,
    resolve_execution_requirements,
    resolve_method_program_binding,
    resolve_research_program_bindings,
    resolve_study_factory_bindings,
)


@dataclass(frozen=True)
class Lane:
    package: str
    method_id: str
    lifecycle: str
    benchmark_ids: tuple[str, ...]
    research_program_digest: str | None
    research_graph_node_id: str | None
    research_graph_semantic_digest: str | None
    study_factory_count: int
    exact_study_factory_count: int
    study_factory_digests: tuple[str, ...]
    execution_requirement_parameters: tuple[str, ...]
    execution_requirement_kinds: tuple[str, ...]
    execution_requirement_digests: tuple[str, ...]
    benchmark_split_axis_consumers: tuple[str, ...]
    method_program_digest: str | None
    research_machine_program_digests: tuple[str, ...]
    state: str
    blockers: tuple[str, ...]


def _lane(definition) -> Lane:
    blockers: list[str] = []
    research_program_digest = None
    graph_node_id = None
    graph_semantic_digest = None
    method_program_digest = None
    machine_program_digests: tuple[str, ...] = ()
    study_factory_digests: tuple[str, ...] = ()
    execution_requirement_parameters: tuple[str, ...] = ()
    execution_requirement_kinds: tuple[str, ...] = ()
    execution_requirement_digests: tuple[str, ...] = ()
    benchmark_split_axis_consumers: tuple[str, ...] = ()
    exact_study_factory_count = 0
    study_factory_count = 0
    try:
        program = compile_reproduction_research_program(definition)
        research_program_digest = program.program_digest
        factories = resolve_study_factory_bindings(definition)
        study_factory_count = len(factories)
        exact_study_factory_count = sum(
            binding.exact_after_benchmark for binding in factories
        )
        study_factory_digests = tuple(
            binding.binding_digest for binding in factories
        )
        requirements = resolve_execution_requirements(definition)
        execution_requirement_parameters = tuple(
            row.parameter for row in requirements
        )
        execution_requirement_kinds = tuple(
            row.kind.value for row in requirements
        )
        execution_requirement_digests = tuple(
            row.requirement_digest for row in requirements
        )
        benchmark_split_axis_consumers = resolve_benchmark_split_consumers(
            definition
        )

        method_assets = tuple(
            row for row in definition.assets
            if row.kind is ReproductionAssetKind.METHOD_PROGRAM
        )
        if method_assets:
            method = resolve_method_program_binding(definition)
            method_program_digest = method.program_digest
        machines = resolve_research_program_bindings(definition)
        machine_program_digests = tuple(
            row.program_digest for row in machines
        )

        portfolio = api.ResearchPortfolio(
            definition.package + ".current-research-os",
            (program,),
        )
        revision = api.ResearchGraphRevision(
            portfolio.portfolio_id,
            portfolio.portfolio_digest,
            (),
            "current Research OS reproduction admission",
        )
        graph = compile_research_portfolio_graph(revision, portfolio)
        node = graph.node(definition.package + "::reproduction")
        graph_node_id = node.graph_node_id
        graph_semantic_digest = node.semantic_digest
    except BaseException as exc:
        blockers.append(type(exc).__name__ + ":" + str(exc))

    compile_failure = any(
        blocker.startswith((
            "ReproductionResearchOSCompileError:",
            "TypeError:",
            "ValueError:",
            "ImportError:",
            "AttributeError:",
        ))
        for blocker in blockers
    )
    return Lane(
        package=definition.package,
        method_id=definition.identity.method_id,
        lifecycle=definition.lifecycle.value,
        benchmark_ids=definition.catalog.benchmark_ids,
        research_program_digest=research_program_digest,
        research_graph_node_id=graph_node_id,
        research_graph_semantic_digest=graph_semantic_digest,
        study_factory_count=study_factory_count,
        exact_study_factory_count=exact_study_factory_count,
        study_factory_digests=study_factory_digests,
        execution_requirement_parameters=execution_requirement_parameters,
        execution_requirement_kinds=execution_requirement_kinds,
        execution_requirement_digests=execution_requirement_digests,
        benchmark_split_axis_consumers=benchmark_split_axis_consumers,
        method_program_digest=method_program_digest,
        research_machine_program_digests=machine_program_digests,
        state=(
            "compile_failed"
            if compile_failure
            else (
                "closure_binding_required"
                if execution_requirement_digests
                else (
                    "benchmark_binding_required"
                    if benchmark_split_axis_consumers
                    else "execution_ready"
                )
            )
        ),
        blockers=tuple(sorted(set(blockers))),
    )


def build_plan() -> dict:
    inventory = discover_reproduction_definitions()
    executable = executable_reproduction_definitions()
    non_executable = tuple(
        row for row in inventory if not is_research_os_executable(row)
    )
    lanes = tuple(
        sorted((_lane(row) for row in executable), key=lambda row: row.package)
    )
    compile_failures = tuple(
        row.package for row in lanes if row.state == "compile_failed"
    )
    if not compile_failures:
        portfolio = build_research()
        if tuple(program.program_id for program in portfolio.programs) != tuple(
            sorted(row.package for row in executable)
        ):
            raise RuntimeError(
                "top-level reproduction ResearchPortfolio drifted from executable "
                "reproduction authority"
            )
        revision = api.ResearchGraphRevision(
            portfolio.portfolio_id,
            portfolio.portfolio_digest,
            (),
            "all executable reproductions on current Research OS",
        )
        graph = compile_research_portfolio_graph(revision, portfolio)
        portfolio_digest = portfolio.portfolio_digest
        graph_digest = graph.plan.graph_digest
        graph_node_count = len(graph.nodes)
    else:
        portfolio_digest = None
        graph_digest = None
        graph_node_count = 0

    document = {
        "schema": "noetrium.reproduction-fleet-plan.v7",
        "inventory_reproduction_count": len(inventory),
        "executable_reproduction_count": len(lanes),
        "non_executable_reproduction_count": len(non_executable),
        "non_executable_packages": tuple(
            row.package for row in non_executable
        ),
        "non_executable_lifecycle": {
            row.package: row.lifecycle.value for row in non_executable
        },
        "research_os_compiled_count": sum(
            row.state != "compile_failed" for row in lanes
        ),
        "execution_ready_count": sum(
            row.state == "execution_ready" for row in lanes
        ),
        "benchmark_binding_required_count": sum(
            row.state == "benchmark_binding_required" for row in lanes
        ),
        "closure_binding_required_count": sum(
            row.state == "closure_binding_required" for row in lanes
        ),
        "compile_failure_count": len(compile_failures),
        "compile_failure_packages": compile_failures,
        "exact_study_binding_count": sum(
            row.exact_study_factory_count > 0 for row in lanes
        ),
        "typed_execution_requirement_count": sum(
            len(row.execution_requirement_digests) for row in lanes
        ),
        "portfolio_digest": portfolio_digest,
        "graph_digest": graph_digest,
        "graph_node_count": graph_node_count,
        "lanes": [asdict(row) for row in lanes],
    }
    document["plan_digest"] = canonical_digest(document)
    return document


def _load_execution_authorities(spec: str) -> ReproductionFleetExecutionAuthorities:
    if type(spec) is not str or not spec.strip() or spec != spec.strip():
        raise ValueError("fleet execution authority spec must be canonical text")
    module_name, separator, qualname = spec.partition(":")
    if (
        separator != ":"
        or not module_name
        or not qualname
        or ":" in qualname
    ):
        raise ValueError(
            "fleet execution authority must use module:factory format"
        )
    module = importlib.import_module(module_name)
    value = module
    for part in qualname.split("."):
        if not part or part.startswith("_"):
            raise ValueError(
                "fleet execution authority factory qualname must be public"
            )
        value = getattr(value, part)
    if not callable(value):
        raise TypeError("fleet execution authority target must be callable")
    authorities = value()
    if type(authorities) is not ReproductionFleetExecutionAuthorities:
        raise TypeError(
            "fleet execution authority factory must return "
            "ReproductionFleetExecutionAuthorities"
        )
    return authorities


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit or execute the complete repository reproduction fleet through "
            "the canonical Research OS authority."
        )
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "resolve exact execution closure and RUN the materialized fleet; "
            "without this flag the command is read-only admission audit"
        ),
    )
    parser.add_argument(
        "--execution-authority",
        help=(
            "module:factory returning ReproductionFleetExecutionAuthorities; "
            "required for --execute and never inferred"
        ),
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=ROOT / ".noetrium" / "reproduction-fleet",
    )
    parser.add_argument("--execution-id")
    args = parser.parse_args()

    if args.execute:
        if args.execution_authority is None:
            parser.error("--execute requires --execution-authority")
        authorities = _load_execution_authorities(args.execution_authority)
        result = run_repository_execution_fleet(
            authorities,
            state_root=args.state_root,
            execution_id=args.execution_id,
        )
        payload = {
            "schema": "noetrium.reproduction-fleet-execution.v1",
            "execution_id": result.receipt.target.execution_id,
            "revision_digest": result.receipt.target.research_revision_digest,
            "materialization_digest": (
                result.materialization.materialization_digest
            ),
            "portfolio_digest": result.materialization.portfolio.portfolio_digest,
            "request_count": len(result.materialization.requests),
            "lane_count": len(result.materialization.lanes),
            "control_action": result.receipt.action.value,
            "control_state": result.receipt.state,
            "control_receipt_digest": result.receipt.receipt_digest,
            "execution_digest": result.execution_digest,
        }
        rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0 if result.receipt.state == "succeeded" else 1

    if args.execution_authority is not None:
        parser.error("--execution-authority is valid only with --execute")
    if args.execution_id is not None:
        parser.error("--execution-id is valid only with --execute")

    payload = build_plan()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps({
        key: payload[key]
        for key in (
            "inventory_reproduction_count",
            "executable_reproduction_count",
            "non_executable_reproduction_count",
            "research_os_compiled_count",
            "compile_failure_count",
            "exact_study_binding_count",
            "execution_ready_count",
            "benchmark_binding_required_count",
            "closure_binding_required_count",
            "typed_execution_requirement_count",
            "plan_digest",
        )
    }, sort_keys=True))
    for row in payload["lanes"]:
        if row["blockers"]:
            print("BINDING_REQUIRED", row["package"], ",".join(row["blockers"]))
    return 0 if payload["compile_failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
