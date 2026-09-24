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
from noetrium_platform.composition.research_binding_authority import (
    ResearchProjectManifestRequirement,
)
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.reproductions import build_research
from research.reproductions.benchmark_authority import RepositoryBenchmarkAuthority
from research.reproductions.contracts import ReproductionAssetKind
from research.reproductions.fleet import (
    ReproductionFleetExecutionAuthorities,
    audit_repository_execution_authorities,
    preflight_repository_execution_fleet,
    run_repository_execution_fleet,
)
from research.reproductions.research_os import (
    compile_reproduction_research_program,
    discover_reproduction_definitions,
    executable_reproduction_definitions,
    is_research_os_executable,
    expand_reproduction_benchmark_lanes,
    materialize_reproduction_study,
    resolve_benchmark_split_consumers,
    resolve_execution_requirements,
    resolve_method_program_binding,
    resolve_research_program_bindings,
    resolve_study_factory_bindings,
)


@dataclass(frozen=True)
class StudyExecutionAuthorityRequirement:
    package: str
    study_factory: str
    benchmark_id: str
    benchmark_split_id: str | None
    project_id: str
    experiment_id: str
    study_id: str
    study_definition_digest: str
    binding_requirement_digest: str
    trial_provider_requirement_id: str
    trial_protocol_identity_digest: str
    aggregation_requirement_id: str
    project_manifest_requirement_digest: str
    project_manifest_capability_requirement_ids: tuple[str, ...]
    project_manifest_method_requirement_keys: tuple[tuple[str, str], ...]
    project_manifest_configuration_ref_ids: tuple[str, ...]
    project_manifest_keys_digest: str
    participant_requirements: tuple[tuple[str, str, str, str, str], ...]
    model_role_requirements: tuple[
        tuple[str, str, str | None, str, bool, int | None, str],
        ...
    ]
    authority_requirement_digest: str


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
    benchmark_authority_state: str
    benchmark_selection_count: int
    benchmark_selection_digests: tuple[str, ...]
    benchmark_blockers: tuple[str, ...]
    reproduction_closure_state: str
    execution_authority_state: str
    materialized_study_count: int
    study_authority_requirements: tuple[StudyExecutionAuthorityRequirement, ...]
    study_authority_requirement_digests: tuple[str, ...]
    materialization_ready: bool
    state: str
    blockers: tuple[str, ...]


def _lane(definition, benchmark_authority: RepositoryBenchmarkAuthority) -> Lane:
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
    benchmark_selection_digests: tuple[str, ...] = ()
    benchmark_blockers: list[str] = []
    benchmark_authority_state = "not_audited"
    reproduction_closure_state = "not_audited"
    execution_authority_state = "required"
    study_authority_requirements: tuple[StudyExecutionAuthorityRequirement, ...] = ()
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
        reproduction_closure_state = (
            "required" if execution_requirement_digests else "closed"
        )

        benchmark_selection_rows = []
        benchmark_selection_by_factory = []
        for factory in factories:
            try:
                selections = benchmark_authority.resolve(definition, factory)
            except BaseException as exc:
                benchmark_blockers.append(
                    type(exc).__name__ + ":" + str(exc)
                )
                continue
            benchmark_selection_rows.extend(selections)
            benchmark_selection_by_factory.append((factory, selections))
        benchmark_selection_digests = tuple(
            sorted(
                row.selection_digest
                for row in benchmark_selection_rows
            )
        )
        benchmark_authority_state = (
            "closed"
            if not benchmark_blockers
            and len(benchmark_selection_rows) >= len(factories)
            else "required"
        )

        if (
            benchmark_authority_state == "closed"
            and reproduction_closure_state == "closed"
        ):
            authority_rows: list[StudyExecutionAuthorityRequirement] = []
            for factory, selections in benchmark_selection_by_factory:
                for selection in selections:
                    bindings = expand_reproduction_benchmark_lanes(
                        definition,
                        study_factory=factory.qualname,
                        benchmark=selection.benchmark,
                        benchmark_split_ids=selection.benchmark_split_ids,
                        values={},
                        resolution_proof_digests=(
                            selection.resolution_proof_digest,
                        ),
                    )
                    for binding in bindings:
                        study = materialize_reproduction_study(
                            definition,
                            binding,
                            selection.benchmark,
                        )
                        requirements = study.binding_requirements
                        project_manifest_requirement = (
                            ResearchProjectManifestRequirement.from_study(study)
                        )
                        participant_requirements = tuple(
                            (
                                row.role,
                                row.participant_kind,
                                row.method_id,
                                row.treatment_id,
                                row.requirement_digest,
                            )
                            for row in requirements.participants
                        )
                        model_role_requirements = tuple(
                            (
                                row.role,
                                row.requirement_id,
                                row.prompt_configuration_id,
                                row.usage.value,
                                row.required,
                                row.max_bindings,
                                row.requirement_digest,
                            )
                            for row in requirements.model_roles
                        )
                        requirement_payload = {
                            "package": definition.package,
                            "study_factory": factory.qualname,
                            "benchmark_id": selection.benchmark.benchmark_id,
                            "benchmark_split_id": binding.benchmark_split_id,
                            "project_id": study.project_id,
                            "experiment_id": study.experiment_id,
                            "study_id": study.study_id,
                            "study_definition_digest": study.definition_digest,
                            "binding_requirement_digest": (
                                study.binding_requirement_digest
                            ),
                            "trial_provider_requirement_id": (
                                requirements.trial_provider_requirement_id
                            ),
                            "trial_protocol_identity_digest": (
                                study.trial_protocol_identity.digest()
                            ),
                            "aggregation_requirement_id": (
                                study.aggregation_requirement_id
                            ),
                            "project_manifest_requirement_digest": (
                                project_manifest_requirement.requirement_digest
                            ),
                            "project_manifest_capability_requirement_ids": (
                                project_manifest_requirement.capability_requirement_ids
                            ),
                            "project_manifest_method_requirement_keys": (
                                project_manifest_requirement.method_requirement_keys
                            ),
                            "project_manifest_configuration_ref_ids": (
                                project_manifest_requirement.configuration_ref_ids
                            ),
                            "project_manifest_keys_digest": (
                                project_manifest_requirement.manifest_keys_digest
                            ),
                            "participant_requirements": participant_requirements,
                            "model_role_requirements": model_role_requirements,
                        }
                        authority_rows.append(
                            StudyExecutionAuthorityRequirement(
                                **requirement_payload,
                                authority_requirement_digest=canonical_digest(
                                    requirement_payload
                                ),
                            )
                        )
            study_authority_requirements = tuple(
                sorted(
                    authority_rows,
                    key=lambda row: row.authority_requirement_digest,
                )
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
        benchmark_authority_state=benchmark_authority_state,
        benchmark_selection_count=len(benchmark_selection_digests),
        benchmark_selection_digests=benchmark_selection_digests,
        benchmark_blockers=tuple(sorted(set(benchmark_blockers))),
        reproduction_closure_state=reproduction_closure_state,
        execution_authority_state=execution_authority_state,
        materialized_study_count=len(study_authority_requirements),
        study_authority_requirements=study_authority_requirements,
        study_authority_requirement_digests=tuple(
            row.authority_requirement_digest
            for row in study_authority_requirements
        ),
        materialization_ready=(
            not compile_failure
            and benchmark_authority_state == "closed"
            and reproduction_closure_state == "closed"
        ),
        state=(
            "compile_failed"
            if compile_failure
            else (
                "benchmark_authority_required"
                if benchmark_authority_state != "closed"
                else (
                    "reproduction_closure_required"
                    if reproduction_closure_state != "closed"
                    else "execution_authority_required"
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
    benchmark_authority = RepositoryBenchmarkAuthority.discover()
    lanes = tuple(
        sorted(
            (_lane(row, benchmark_authority) for row in executable),
            key=lambda row: row.package,
        )
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
        "schema": "noetrium.reproduction-fleet-plan.v9",
        "benchmark_authority_digest": benchmark_authority.authority_digest,
        "benchmark_authority_binding_count": len(benchmark_authority.bindings),
        "benchmark_authority_discovery_failure_count": len(
            benchmark_authority.failures
        ),
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
        "benchmark_authority_required_count": sum(
            row.benchmark_authority_state == "required" for row in lanes
        ),
        "reproduction_closure_required_count": sum(
            row.reproduction_closure_state == "required" for row in lanes
        ),
        "materialization_ready_count": sum(
            row.materialization_ready for row in lanes
        ),
        "execution_authority_required_count": sum(
            row.materialization_ready
            and row.execution_authority_state == "required"
            for row in lanes
        ),
        "materialized_study_count": sum(
            row.materialized_study_count for row in lanes
        ),
        "study_authority_requirement_count": sum(
            len(row.study_authority_requirement_digests) for row in lanes
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--authority-audit",
        action="store_true",
        help=(
            "materialize exact benchmark/reproduction closure and aggregate "
            "all lane-level Research/Study/aggregation/reconciliation authority "
            "gaps without creating stores, cuts, or tasks"
        ),
    )
    mode.add_argument(
        "--preflight",
        action="store_true",
        help=(
            "resolve exact closure and run canonical whole-graph admission "
            "without creating an execution cut or starting tasks"
        ),
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help=(
            "resolve exact execution closure and RUN the materialized fleet; "
            "without either mode flag the command is a static authority audit"
        ),
    )
    parser.add_argument(
        "--execution-authority",
        help=(
            "module:factory returning ReproductionFleetExecutionAuthorities; "
            "required for --authority-audit/--preflight/--execute and never inferred"
        ),
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=ROOT / ".noetrium" / "reproduction-fleet",
    )
    parser.add_argument("--execution-id")
    args = parser.parse_args()

    if args.authority_audit:
        if args.execution_authority is None:
            parser.error("--authority-audit requires --execution-authority")
        authorities = _load_execution_authorities(args.execution_authority)
        result = audit_repository_execution_authorities(authorities)
        payload = {
            "schema": "noetrium.reproduction-fleet-authority-audit.v1",
            "materialization_digest": (
                result.materialization.materialization_digest
            ),
            "portfolio_digest": result.materialization.portfolio.portfolio_digest,
            "revision_digest": result.revision_digest,
            "lane_count": len(result.lanes),
            "closed_lane_count": result.closed_lane_count,
            "blocker_count": result.blocker_count,
            "gap_count": result.gap_count,
            "all_execution_authority_closed": (
                result.closed_lane_count == len(result.lanes)
            ),
            "audit_digest": result.audit_digest,
            "lanes": [
                {
                    "package": row.package,
                    "program_id": row.program_id,
                    "graph_node_id": row.graph_node_id,
                    "closure_digest": row.closure_digest,
                    "research_binding_closed": row.research_binding_closed,
                    "study_execution_closed": row.study_execution_closed,
                    "aggregation_closed": row.aggregation_closed,
                    "reconciliation_closed": row.reconciliation_closed,
                    "execution_authority_closed": (
                        row.execution_authority_closed
                    ),
                    "gaps": [
                        {
                            "stage": gap.stage,
                            "requirement_key": gap.requirement_key,
                            "requirement_digest": gap.requirement_digest,
                            "error_type": gap.error_type,
                            "message": gap.message,
                            "diagnostics": gap.diagnostics,
                            "gap_digest": gap.gap_digest,
                        }
                        for gap in row.gaps
                    ],
                    "blockers": row.blockers,
                    "audit_digest": row.audit_digest,
                }
                for row in result.lanes
            ],
        }
        rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0 if payload["all_execution_authority_closed"] else 1

    if args.preflight:
        if args.execution_authority is None:
            parser.error("--preflight requires --execution-authority")
        authorities = _load_execution_authorities(args.execution_authority)
        result = preflight_repository_execution_fleet(
            authorities,
            state_root=args.state_root,
            execution_id=args.execution_id,
        )
        payload = {
            "schema": "noetrium.reproduction-fleet-preflight.v1",
            "execution_id": result.execution_id,
            "revision_digest": result.revision_digest,
            "materialization_digest": result.materialization.materialization_digest,
            "portfolio_digest": result.materialization.portfolio.portfolio_digest,
            "request_count": len(result.materialization.requests),
            "lane_count": len(result.materialization.lanes),
            "selected_node_count": len(result.selected_node_ids),
            "admission_count": len(result.admission_digests),
            "preflight_digest": result.preflight_digest,
            "result_digest": result.result_digest,
        }
        rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0

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
        parser.error(
            "--execution-authority requires --authority-audit, --preflight, "
            "or --execute"
        )
    if args.execution_id is not None:
        parser.error("--execution-id requires --preflight or --execute")

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
            "benchmark_authority_required_count",
            "reproduction_closure_required_count",
            "materialization_ready_count",
            "execution_authority_required_count",
            "materialized_study_count",
            "study_authority_requirement_count",
            "typed_execution_requirement_count",
            "plan_digest",
        )
    }, sort_keys=True))
    for row in payload["lanes"]:
        reasons = tuple(row["blockers"]) + tuple(row["benchmark_blockers"])
        if row["reproduction_closure_state"] == "required":
            reasons += ("typed-reproduction-closure-required",)
        if reasons:
            print("BINDING_REQUIRED", row["package"], ",".join(reasons))
    return 0 if payload["compile_failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
