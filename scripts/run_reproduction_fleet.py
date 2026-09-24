from __future__ import annotations

import argparse
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
from research.reproductions.research_os import (
    compile_reproduction_research_program,
    executable_reproduction_definitions,
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
        method_program_digest=method_program_digest,
        research_machine_program_digests=machine_program_digests,
        state=(
            "compile_failed"
            if compile_failure
            else (
                "closure_binding_required"
                if execution_requirement_digests
                else "execution_ready"
            )
        ),
        blockers=tuple(sorted(set(blockers))),
    )


def build_plan() -> dict:
    executable = executable_reproduction_definitions()
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
        "schema": "noetrium.reproduction-fleet-plan.v5",
        "executable_reproduction_count": len(lanes),
        "research_os_compiled_count": sum(
            row.state != "compile_failed" for row in lanes
        ),
        "execution_ready_count": sum(
            row.state == "execution_ready" for row in lanes
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compile every protocol-bound paper reproduction through the current "
            "Research OS authority and emit its exact admission state."
        )
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = build_plan()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps({
        key: payload[key]
        for key in (
            "executable_reproduction_count",
            "research_os_compiled_count",
            "compile_failure_count",
            "exact_study_binding_count",
            "execution_ready_count",
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
