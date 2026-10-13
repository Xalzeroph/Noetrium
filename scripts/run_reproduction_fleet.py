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

from noetrium_platform.product.research_control import ResearchGraphRevision
from noetrium_platform.composition.research_authority_inputs import (
    normalize_authority_inputs,
)
from noetrium_platform.composition.research_binding_authority import (
    research_project_manifest_requirement,
)
from noetrium_platform.composition.research_portfolio_execution import (
    ResearchExecutionContext,
    open_local_research_execution_context,
)
from noetrium_platform.composition.research_execution_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.reproductions import build_research
from research.reproductions.authority_requirements import (
    compile_materialized_fleet_owner_requirements,
    compile_repository_fleet_prerequisites,
)
from research.reproductions.repository_authority import (
    build_repository_fleet_authority_materializer,
)
from research.reproductions.benchmark_authority import RepositoryBenchmarkAuthority
from research.reproductions.contracts import ReproductionAssetKind
from research.reproductions.execution_authority import (
    ReproductionFleetAuthorityMaterializerPort,
    materialize_repository_fleet_execution_authorities,
)
from research.reproductions.fleet import (
    audit_materialized_reproduction_fleet_authorities,
    select_execution_authority_closed_fleet,
)
from research.reproductions.research_units import (
    compile_reproduction_portfolio,
    compile_reproduction_research_program,
    discover_reproduction_definitions,
    executable_reproduction_definitions,
    expand_reproduction_benchmark_lanes,
    is_research_executable,
    materialize_reproduction_study,
    resolve_benchmark_split_consumers,
    resolve_execution_requirements,
    resolve_method_binding,
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
        research_program_digest = program.unit_digest
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
                            research_project_manifest_requirement(study)
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
            method = resolve_method_binding(definition)
            method_program_digest = method.method_digest
        portfolio = compile_reproduction_portfolio(
            definition.package + ".current-research",
            (definition,),
        )
        revision = ResearchGraphRevision(
            portfolio.unit_id,
            portfolio.unit_digest,
            (),
            "current Research execution reproduction admission",
        )
        graph = compile_research_portfolio_graph(revision, portfolio)
        node = graph.binding(portfolio.unit_id + "::" + definition.package + "::reproduction")
        graph_node_id = node.graph_node_id
        graph_semantic_digest = node.semantic_digest
    except BaseException as exc:
        blockers.append(type(exc).__name__ + ":" + str(exc))

    compile_failure = any(
        blocker.startswith((
            "ReproductionResearchCompileError:",
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
        row for row in inventory if not is_research_executable(row)
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
        if tuple(sorted(program.graph_id for program in portfolio.units_with_schema("research.program"))) != tuple(
            sorted(row.package for row in executable)
        ):
            raise RuntimeError(
                "top-level reproduction Unit root drifted from executable "
                "reproduction authority"
            )
        revision = ResearchGraphRevision(
            portfolio.unit_id,
            portfolio.unit_digest,
            (),
            "all executable reproductions on current Research execution",
        )
        graph = compile_research_portfolio_graph(revision, portfolio)
        portfolio_digest = portfolio.unit_digest
        graph_digest = graph.graph_digest
        graph_node_count = len(graph.nodes_by_id)
    else:
        portfolio_digest = None
        graph_digest = None
        graph_node_count = 0

    prerequisites = compile_repository_fleet_prerequisites()
    document = {
        "schema": "noetrium.reproduction-fleet-plan.v10",
        "prerequisite_manifest_digest": prerequisites.manifest_digest,
        "prerequisite_requirement_count": len(prerequisites.requirements),
        "prerequisite_stage_counts": {
            stage: sum(row.stage == stage for row in prerequisites.requirements)
            for stage in sorted({row.stage for row in prerequisites.requirements})
        },
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
        "research_compiled_count": sum(
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



def _audit_source(
    args,
    parser,
    context: ResearchExecutionContext,
):
    materializer = build_repository_fleet_authority_materializer(context)
    materialized = materialize_repository_fleet_execution_authorities(
        materializer,
        require_full_closure=False,
    )
    return materialized

def _parse_authority_inputs(rows: list[str], parser) -> tuple[tuple[str, str], ...]:
    parsed: list[tuple[str, str]] = []
    for raw in rows:
        key, separator, value = raw.partition("=")
        if separator != "=":
            parser.error("--authority-input must use KEY=VALUE")
        parsed.append((key, value))
    try:
        return normalize_authority_inputs(
            tuple(parsed),
            label="fleet audit authority_inputs",
        )
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
        raise AssertionError("unreachable") from exc


def _write_payload(payload: dict[str, object], output: Path | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Discover, materialize and audit the repository reproduction inventory. "
            "Execution is owned exclusively by the canonical Research root runner."
        )
    )
    parser.add_argument("--output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--requirements",
        action="store_true",
        help="emit the content-addressed repository prerequisite manifest",
    )
    mode.add_argument(
        "--authority-audit",
        action="store_true",
        help="resolve all lane-level authority gaps without creating an execution cut",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=ROOT / ".noetrium" / "reproduction-fleet",
    )
    parser.add_argument(
        "--authority-input",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="explicit machine-local authority fact; accepted only for authority audit",
    )
    args = parser.parse_args()
    authority_inputs = _parse_authority_inputs(args.authority_input, parser)

    if args.requirements:
        if authority_inputs:
            parser.error("--requirements does not accept --authority-input")
        manifest = compile_repository_fleet_prerequisites()
        payload = {
            "schema": "noetrium.reproduction-fleet-prerequisites.v1",
            "manifest_digest": manifest.manifest_digest,
            "requirement_count": len(manifest.requirements),
            "stage_counts": {
                stage: sum(row.stage == stage for row in manifest.requirements)
                for stage in sorted({row.stage for row in manifest.requirements})
            },
            "owner_counts": {
                owner: sum(row.owner == owner for row in manifest.requirements)
                for owner in sorted({row.owner for row in manifest.requirements})
            },
            "requirements": [asdict(row) for row in manifest.requirements],
        }
        _write_payload(payload, args.output)
        return 0

    if args.authority_audit:
        with open_local_research_execution_context(
            args.state_root,
            authority_inputs=authority_inputs,
        ) as context:
            materialized = _audit_source(args, parser, context)
            authorities = materialized.execution_authorities
            result = audit_materialized_reproduction_fleet_authorities(
                materialized.fleet,
                research_bindings=authorities.research_bindings,
                experiment_runtime_binding=authorities.experiment_runtime_binding,
                authority_manifest_digest=authorities.authority_manifest_digest,
            )
        owner_requirements = compile_materialized_fleet_owner_requirements(
            result.materialization
        )
        payload = {
            "schema": "noetrium.reproduction-fleet-authority-audit.v3",
            "authority_manifest_digest": result.authority_manifest_digest,
            "authority_materialization_digest": materialized.materialization_digest,
            "materialization_digest": result.materialization.materialization_digest,
            "owner_requirement_manifest_digest": owner_requirements.manifest_digest,
            "owner_requirement_count": len(owner_requirements.requirements),
            "revision_digest": result.revision_digest,
            "lane_count": len(result.lanes),
            "closed_lane_count": result.closed_lane_count,
            "blocker_count": result.blocker_count,
            "gap_count": result.gap_count,
            "audit_digest": result.audit_digest,
            "lanes": [
                {
                    "package": row.package,
                    "program_id": row.program_id,
                    "graph_node_id": row.graph_node_id,
                    "execution_binding_digest": row.execution_binding_digest,
                    "execution_authority_closed": row.execution_authority_closed,
                    "gap_digests": tuple(gap.gap_digest for gap in row.gaps),
                    "blockers": row.blockers,
                    "audit_digest": row.audit_digest,
                }
                for row in result.lanes
            ],
        }
        _write_payload(payload, args.output)
        return 0 if result.gap_count == 0 and result.blocker_count == 0 else 1

    if authority_inputs:
        parser.error("--authority-input requires --authority-audit")
    payload = build_plan()
    _write_payload(payload, args.output)
    return 0 if payload["compile_failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
