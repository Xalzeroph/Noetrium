"""Exact fleet materialization for repository reproductions.

Paper packages own scientific semantics. This module only joins immutable
benchmark authority, typed capability closure and existing Research execution lowering.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from noetrium_platform.product.research_control import (
    ResearchGraphRevision,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.composition.research_binding_authority import (
    ResearchBindingAuthorityError,
    ResearchBindingAuthorityPort,
    ResearchBindingRequirementMissing,
    research_project_manifest_requirement,
)
from noetrium_platform.composition.research_execution_pool import (
    ResearchExecutionPool,
)
from noetrium_platform.composition.research_experiment_runtime_binding import (
    ResearchExperimentRuntimeBindingAuthority,
)
from noetrium_platform.composition.research_execution_graph import (
    ResearchExecutionBinding,
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.research_lowering import (
    ResearchExecutionBindingCompiler,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.api import (
    ResearchBindingContribution,
    ResearchManifestRequirementsUnresolved,
    ResearchRequirementResolution,
    compile_experiment_program,
    compile_research_plan,
    research_plan_study,
    research_plan_trial_protocol_identity,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    benchmark_cut_digest,
    benchmark_id,
    benchmark_revision_id,
    benchmark_splits,
    require_benchmark_unit,
    require_study_unit,
    split_id,
    study_benchmark,
    study_benchmark_split_id,
    study_definition_digest,
    study_binding_requirement_digest,
    study_id,
    study_plan_provider_id,
    study_project_id,
)

from .contracts import ReproductionDefinition
from .research_units import (
    ReproductionCapabilityRequirementResolverPort,
    ReproductionExecutionBinding,
    ReproductionExecutionRequest,
    ReproductionResearchCompileError,
    ReproductionStudyFactoryBinding,
    bound_reproduction_program_id,
    compile_bound_reproduction_portfolio,
    compile_bound_reproduction_research_program,
    executable_reproduction_definitions,
    expand_resolved_reproduction_benchmark_lanes,
    materialize_reproduction_study,
    resolve_benchmark_split_consumers,
    resolve_study_factory_bindings,
)


def _require_sha256(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class ReproductionBenchmarkSelection:
    """One immutable benchmark cut plus the paper-authoritative split subset."""

    benchmark: NoetriumUnit
    benchmark_split_ids: tuple[str, ...]
    resolution_proof_digest: str
    selection_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_benchmark_unit(self.benchmark)
        if type(self.benchmark_split_ids) is not tuple:
            raise TypeError("benchmark selection split ids must be tuple")
        if (
            tuple(sorted(self.benchmark_split_ids)) != self.benchmark_split_ids
            or len(self.benchmark_split_ids) != len(set(self.benchmark_split_ids))
            or any(
                type(split_id) is not str
                or not split_id.strip()
                or split_id != split_id.strip()
                for split_id in self.benchmark_split_ids
            )
        ):
            raise ValueError(
                "benchmark selection split ids must be unique canonical text "
                "in sorted order"
            )
        declared = {split_id(row) for row in benchmark_splits(self.benchmark)}
        unknown = tuple(
            split_id
            for split_id in self.benchmark_split_ids
            if split_id not in declared
        )
        if unknown:
            raise ValueError(
                f"benchmark selection references unknown splits: {unknown}"
            )
        _require_sha256(
            self.resolution_proof_digest,
            "benchmark selection resolution proof",
        )
        object.__setattr__(
            self,
            "selection_digest",
            canonical_digest(
                {
                    "benchmark_id": benchmark_id(self.benchmark),
                    "benchmark_revision_id": benchmark_revision_id(self.benchmark),
                    "benchmark_cut_digest": benchmark_cut_digest(self.benchmark),
                    "benchmark_split_ids": self.benchmark_split_ids,
                    "resolution_proof_digest": self.resolution_proof_digest,
                }
            ),
        )


@runtime_checkable
class ReproductionBenchmarkResolverPort(Protocol):
    """Resolve exact benchmark cuts/splits from an identity-bearing authority."""

    @property
    def authority_digest(self) -> str: ...

    def resolve(
        self,
        definition: ReproductionDefinition,
        study_factory: ReproductionStudyFactoryBinding,
    ) -> tuple[ReproductionBenchmarkSelection, ...]: ...


@dataclass(frozen=True, slots=True)
class ReproductionFleetLane:
    definition: ReproductionDefinition
    request: ReproductionExecutionRequest
    binding: ReproductionExecutionBinding
    study: NoetriumUnit
    program: object
    lane_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.definition) is not ReproductionDefinition:
            raise TypeError("fleet lane requires ReproductionDefinition")
        if type(self.request) is not ReproductionExecutionRequest:
            raise TypeError("fleet lane requires ReproductionExecutionRequest")
        if type(self.binding) is not ReproductionExecutionBinding:
            raise TypeError("fleet lane requires ReproductionExecutionBinding")
        require_study_unit(self.study)
        if type(self.program) is not NoetriumUnit:
            raise TypeError("fleet lane requires NoetriumUnit")
        if (
            self.definition.package != self.request.package
            or self.definition.package != self.binding.package
        ):
            raise ValueError("fleet lane package identity drifted")
        if self.binding.study_factory != self.request.study_factory:
            raise ValueError("fleet lane Study factory drifted")
        if self.binding.benchmark_id != benchmark_id(self.request.benchmark):
            raise ValueError("fleet lane benchmark identity drifted")
        if benchmark_cut_digest(study_benchmark(self.study)) != benchmark_cut_digest(self.request.benchmark):
            raise ValueError("fleet lane Study benchmark cut drifted")
        if (
            self.binding.benchmark_split_id is not None
            and study_benchmark_split_id(self.study) != self.binding.benchmark_split_id
        ):
            raise ValueError("fleet lane Study split identity drifted")
        expected_program_id = bound_reproduction_program_id(
            self.definition,
            self.binding,
        )
        if self.program.unit_id != expected_program_id:
            raise ValueError("fleet lane NoetriumUnit identity drifted")
        object.__setattr__(
            self,
            "lane_digest",
            canonical_digest(
                {
                    "definition_digest": self.definition.definition_digest,
                    "request_digest": self.request.request_digest,
                    "binding_digest": self.binding.binding_digest,
                    "study_definition_digest": study_definition_digest(self.study),
                    "program_digest": self.program.unit_digest,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ReproductionFleetMaterialization:
    requests: tuple[ReproductionExecutionRequest, ...]
    lanes: tuple[ReproductionFleetLane, ...]
    portfolio: NoetriumUnit
    materialization_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.requests) is not tuple or not self.requests:
            raise ValueError("fleet materialization requires requests")
        if any(type(row) is not ReproductionExecutionRequest for row in self.requests):
            raise TypeError("fleet materialization requests must be typed")
        if type(self.lanes) is not tuple or not self.lanes:
            raise ValueError("fleet materialization requires lanes")
        if any(type(row) is not ReproductionFleetLane for row in self.lanes):
            raise TypeError("fleet materialization lanes must be typed")
        if type(self.portfolio) is not NoetriumUnit:
            raise TypeError("fleet materialization requires NoetriumUnit")
        if not self.portfolio.has_trait("research.portfolio"):
            raise ValueError("fleet materialization requires research.portfolio root")

        request_digests = tuple(row.request_digest for row in self.requests)
        lane_digests = tuple(row.lane_digest for row in self.lanes)
        if len(request_digests) != len(set(request_digests)):
            raise ValueError("fleet requests must be unique")
        if len(lane_digests) != len(set(lane_digests)):
            raise ValueError("fleet lanes must be unique")

        program_ids = tuple(row.program.unit_id for row in self.lanes)
        if program_ids != tuple(sorted(program_ids)):
            raise ValueError("fleet lanes must be canonically ordered")
        if len(program_ids) != len(set(program_ids)):
            raise ValueError("fleet NoetriumUnit identities must be unique")
        if tuple(sorted(row.unit_id for row in self.portfolio.units_with_schema("research.program"))) != program_ids:
            raise ValueError("fleet portfolio drifted from materialized lanes")

        object.__setattr__(
            self,
            "materialization_digest",
            canonical_digest(
                {
                    "request_digests": request_digests,
                    "lane_digests": lane_digests,
                    "portfolio_digest": self.portfolio.unit_digest,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ReproductionFleetMaterializationBlocker:
    """One independently blocked repository reproduction or execution request."""

    package: str
    stage: str
    error_type: str
    message: str
    requirement_digest: str
    blocker_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in ("package", "stage", "error_type"):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip() or value != value.strip():
                raise ValueError(
                    f"fleet materialization blocker {field_name} must be canonical text"
                )
        if type(self.message) is not str:
            raise TypeError("fleet materialization blocker message must be text")
        _require_sha256(
            self.requirement_digest,
            "fleet materialization blocker requirement_digest",
        )
        object.__setattr__(
            self,
            "blocker_digest",
            canonical_digest(
                {
                    "package": self.package,
                    "stage": self.stage,
                    "error_type": self.error_type,
                    "message": self.message,
                    "requirement_digest": self.requirement_digest,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class PartialReproductionFleetMaterialization:
    """Runnable repository subgraph plus independently blocked source lanes."""

    materialization: ReproductionFleetMaterialization | None
    blockers: tuple[ReproductionFleetMaterializationBlocker, ...]
    discovery_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            self.materialization is not None
            and type(self.materialization) is not ReproductionFleetMaterialization
        ):
            raise TypeError(
                "partial fleet materialization must contain typed materialization"
            )
        if type(self.blockers) is not tuple or any(
            type(row) is not ReproductionFleetMaterializationBlocker
            for row in self.blockers
        ):
            raise TypeError("partial fleet blockers must be typed immutable tuple")
        ordered = tuple(sorted(self.blockers, key=lambda row: row.blocker_digest))
        if len({row.blocker_digest for row in ordered}) != len(ordered):
            raise ValueError("partial fleet blockers must be unique")
        object.__setattr__(self, "blockers", ordered)
        object.__setattr__(
            self,
            "discovery_digest",
            canonical_digest(
                {
                    "materialization_digest": (
                        None
                        if self.materialization is None
                        else self.materialization.materialization_digest
                    ),
                    "blockers": tuple(row.blocker_digest for row in ordered),
                }
            ),
        )

    @property
    def runnable_lane_count(self) -> int:
        return (
            0
            if self.materialization is None
            else len(self.materialization.lanes)
        )


def _resolve_definition_execution_requests(
    definition: ReproductionDefinition,
    benchmark_resolver: ReproductionBenchmarkResolverPort,
) -> tuple[ReproductionExecutionRequest, ...]:
    factories = resolve_study_factory_bindings(definition)
    split_consumers = set(resolve_benchmark_split_consumers(definition))
    method_split_axis = any(
        consumer.startswith("method:")
        for consumer in split_consumers
    )
    requests: list[ReproductionExecutionRequest] = []
    covered_benchmarks: set[str] = set()

    for factory in factories:
        selections = benchmark_resolver.resolve(definition, factory)
        if type(selections) is not tuple or not selections:
            raise ReproductionResearchCompileError(
                f"{definition.package} Study {factory.qualname} has no "
                "exact benchmark selection"
            )
        if any(
            type(row) is not ReproductionBenchmarkSelection
            for row in selections
        ):
            raise TypeError(
                f"{definition.package} benchmark resolver returned "
                "untyped selection"
            )
        selection_digests = tuple(row.selection_digest for row in selections)
        if len(selection_digests) != len(set(selection_digests)):
            raise ReproductionResearchCompileError(
                f"{definition.package} Study {factory.qualname} returned "
                "duplicate benchmark selections"
            )

        split_aware = (
            method_split_axis
            or f"study:{factory.qualname}" in split_consumers
        )
        for selection in sorted(
            selections,
            key=lambda row: row.selection_digest,
        ):
            benchmark_id_value = benchmark_id(selection.benchmark)
            if benchmark_id_value not in definition.catalog.benchmark_ids:
                raise ReproductionResearchCompileError(
                    f"{definition.package} benchmark authority returned "
                    f"out-of-catalog benchmark {benchmark_id_value!r}"
                )
            if split_aware and not selection.benchmark_split_ids:
                raise ReproductionResearchCompileError(
                    f"{definition.package} Study {factory.qualname} "
                    "requires explicit benchmark split selection"
                )
            if not split_aware and selection.benchmark_split_ids:
                raise ReproductionResearchCompileError(
                    f"{definition.package} Study {factory.qualname} has "
                    "no external benchmark split axis"
                )
            requests.append(
                ReproductionExecutionRequest(
                    definition.package,
                    factory.qualname,
                    selection.benchmark,
                    selection.benchmark_split_ids,
                    selection.resolution_proof_digest,
                )
            )
            covered_benchmarks.add(benchmark_id_value)

    missing = tuple(
        sorted(set(definition.catalog.benchmark_ids) - covered_benchmarks)
    )
    if missing:
        raise ReproductionResearchCompileError(
            f"{definition.package} benchmark authority did not close "
            f"catalog benchmarks: {missing}"
        )
    return tuple(requests)


def resolve_repository_execution_requests(
    benchmark_resolver: ReproductionBenchmarkResolverPort,
) -> tuple[ReproductionExecutionRequest, ...]:
    """Discover every executable reproduction and close its benchmark authority."""

    if not isinstance(benchmark_resolver, ReproductionBenchmarkResolverPort):
        raise TypeError("fleet requires ReproductionBenchmarkResolverPort")
    _require_sha256(
        benchmark_resolver.authority_digest,
        "fleet benchmark authority_digest",
    )

    requests = tuple(
        request
        for definition in executable_reproduction_definitions()
        for request in _resolve_definition_execution_requests(
            definition,
            benchmark_resolver,
        )
    )
    ordered = tuple(
        sorted(
            requests,
            key=lambda row: (
                row.package,
                row.study_factory,
                benchmark_id(row.benchmark),
                benchmark_revision_id(row.benchmark),
                benchmark_cut_digest(row.benchmark),
                row.benchmark_split_ids,
                row.benchmark_resolution_proof_digest,
            ),
        )
    )
    digests = tuple(row.request_digest for row in ordered)
    if len(digests) != len(set(digests)):
        raise ReproductionResearchCompileError(
            "fleet execution request identities must be unique"
        )
    return ordered


def materialize_runnable_repository_execution_fleet(
    benchmark_resolver: ReproductionBenchmarkResolverPort,
    *,
    capability_resolver: ReproductionCapabilityRequirementResolverPort | None = None,
    portfolio_id: str = "repository-reproductions.runnable-execution",
) -> PartialReproductionFleetMaterialization:
    """Materialize every independently closed lane and retain exact blockers.

    This is the zero-glue launch path: missing benchmark/capability authority for
    one paper cannot prevent unrelated closed papers from entering the Research
    OS execution portfolio.
    """

    if not isinstance(benchmark_resolver, ReproductionBenchmarkResolverPort):
        raise TypeError("partial fleet requires ReproductionBenchmarkResolverPort")
    if capability_resolver is not None and not isinstance(
        capability_resolver,
        ReproductionCapabilityRequirementResolverPort,
    ):
        raise TypeError(
            "partial fleet capability_resolver must satisfy typed resolver port"
        )

    definitions = {
        row.package: row
        for row in executable_reproduction_definitions()
    }
    requests: list[ReproductionExecutionRequest] = []
    lanes: list[ReproductionFleetLane] = []
    blockers: list[ReproductionFleetMaterializationBlocker] = []

    for package in sorted(definitions):
        definition = definitions[package]
        try:
            definition_requests = _resolve_definition_execution_requests(
                definition,
                benchmark_resolver,
            )
        except BaseException as exc:
            blockers.append(
                ReproductionFleetMaterializationBlocker(
                    package,
                    "benchmark",
                    type(exc).__name__,
                    str(exc),
                    canonical_digest(
                        {
                            "stage": "benchmark",
                            "definition_digest": definition.definition_digest,
                        }
                    ),
                )
            )
            continue

        for request in definition_requests:
            try:
                bindings = expand_resolved_reproduction_benchmark_lanes(
                    definition,
                    study_factory=request.study_factory,
                    benchmark=request.benchmark,
                    benchmark_split_ids=request.benchmark_split_ids,
                    benchmark_resolution_proof_digest=(
                        request.benchmark_resolution_proof_digest
                    ),
                    capability_resolver=capability_resolver,
                )
                if not bindings:
                    raise ReproductionResearchCompileError(
                        f"{request.package} execution request produced no lanes"
                    )
                materialized_any = False
                for binding in bindings:
                    study = materialize_reproduction_study(
                        definition,
                        binding,
                        request.benchmark,
                    )
                    program = compile_bound_reproduction_research_program(
                        definition,
                        binding,
                    )
                    lanes.append(
                        ReproductionFleetLane(
                            definition,
                            request,
                            binding,
                            study,
                            program,
                        )
                    )
                    materialized_any = True
                if materialized_any:
                    requests.append(request)
            except BaseException as exc:
                blockers.append(
                    ReproductionFleetMaterializationBlocker(
                        package,
                        "reproduction_closure",
                        type(exc).__name__,
                        str(exc),
                        canonical_digest(
                            {
                                "stage": "reproduction_closure",
                                "request_digest": request.request_digest,
                            }
                        ),
                    )
                )

    ordered_lanes = tuple(
        sorted(lanes, key=lambda row: row.program.unit_id)
    )
    materialization = None
    if ordered_lanes:
        represented_request_digests = {
            lane.request.request_digest for lane in ordered_lanes
        }
        ordered_requests = tuple(
            sorted(
                (
                    row
                    for row in requests
                    if row.request_digest in represented_request_digests
                ),
                key=lambda row: row.request_digest,
            )
        )
        materialization = ReproductionFleetMaterialization(
            ordered_requests,
            ordered_lanes,
            compile_bound_reproduction_portfolio(
                portfolio_id,
                tuple(row.binding for row in ordered_lanes),
            ),
        )

    return PartialReproductionFleetMaterialization(
        materialization,
        tuple(blockers),
    )


def materialize_repository_execution_fleet(
    benchmark_resolver: ReproductionBenchmarkResolverPort,
    *,
    capability_resolver: ReproductionCapabilityRequirementResolverPort | None = None,
    portfolio_id: str = "repository-reproductions.materialized-execution",
) -> ReproductionFleetMaterialization:
    """Resolve benchmark/capability closure, materialize Study, compile Portfolio."""

    if capability_resolver is not None and not isinstance(
        capability_resolver,
        ReproductionCapabilityRequirementResolverPort,
    ):
        raise TypeError(
            "fleet capability_resolver must satisfy typed resolver port"
        )
    requests = resolve_repository_execution_requests(benchmark_resolver)
    definitions = {
        row.package: row
        for row in executable_reproduction_definitions()
    }
    lanes: list[ReproductionFleetLane] = []

    for request in requests:
        definition = definitions[request.package]
        bindings = expand_resolved_reproduction_benchmark_lanes(
            definition,
            study_factory=request.study_factory,
            benchmark=request.benchmark,
            benchmark_split_ids=request.benchmark_split_ids,
            benchmark_resolution_proof_digest=(
                request.benchmark_resolution_proof_digest
            ),
            capability_resolver=capability_resolver,
        )
        if not bindings:
            raise ReproductionResearchCompileError(
                f"{request.package} execution request produced no lanes"
            )
        for binding in bindings:
            study = materialize_reproduction_study(
                definition,
                binding,
                request.benchmark,
            )
            program = compile_bound_reproduction_research_program(
                definition,
                binding,
            )
            lanes.append(
                ReproductionFleetLane(
                    definition,
                    request,
                    binding,
                    study,
                    program,
                )
            )

    ordered_lanes = tuple(
        sorted(lanes, key=lambda row: row.program.unit_id)
    )
    portfolio = compile_bound_reproduction_portfolio(
        portfolio_id,
        tuple(row.binding for row in ordered_lanes),
    )
    return ReproductionFleetMaterialization(
        requests,
        ordered_lanes,
        portfolio,
    )


def _fleet_execution_id(
    fleet: ReproductionFleetMaterialization,
    authority_manifest_digest: str,
    execution_id: str | None,
) -> str:
    if type(fleet) is not ReproductionFleetMaterialization:
        raise TypeError("fleet execution requires ReproductionFleetMaterialization")
    _require_sha256(
        authority_manifest_digest,
        "fleet execution authority_manifest_digest",
    )
    resolved = (
        "repository-reproductions."
        + canonical_digest(
            {
                "materialization_digest": fleet.materialization_digest,
                "authority_manifest_digest": authority_manifest_digest,
            }
        )[:24]
        if execution_id is None
        else execution_id
    )
    if (
        type(resolved) is not str
        or not resolved.strip()
        or resolved != resolved.strip()
    ):
        raise ValueError("fleet execution_id must be canonical non-empty text")
    return resolved


def _fleet_revision_message(
    fleet: ReproductionFleetMaterialization,
    authority_manifest_digest: str,
) -> str:
    if type(fleet) is not ReproductionFleetMaterialization:
        raise TypeError("fleet revision requires ReproductionFleetMaterialization")
    _require_sha256(
        authority_manifest_digest,
        "fleet revision authority_manifest_digest",
    )
    return (
        "repository reproduction fleet "
        + canonical_digest(
            {
                "materialization_digest": fleet.materialization_digest,
                "authority_manifest_digest": authority_manifest_digest,
            }
        )
    )


@dataclass(frozen=True, slots=True)
class ReproductionFleetAuthorityGap:
    """Machine-readable missing execution authority for one materialized lane."""

    stage: str
    requirement_key: str
    requirement_digest: str
    error_type: str
    message: str
    diagnostics: tuple[str, ...] = ()
    gap_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("stage", self.stage),
            ("requirement_key", self.requirement_key),
            ("error_type", self.error_type),
        ):
            if (
                type(value) is not str
                or not value.strip()
                or value != value.strip()
            ):
                raise ValueError(
                    f"fleet authority gap {field_name} must be canonical text"
                )
        _require_sha256(
            self.requirement_digest,
            "fleet authority gap requirement_digest",
        )
        if type(self.message) is not str:
            raise TypeError("fleet authority gap message must be text")
        if type(self.diagnostics) is not tuple or any(
            type(row) is not str or not row
            for row in self.diagnostics
        ):
            raise TypeError(
                "fleet authority gap diagnostics must be immutable text tuple"
            )
        object.__setattr__(
            self,
            "gap_digest",
            canonical_digest(
                {
                    "stage": self.stage,
                    "requirement_key": self.requirement_key,
                    "requirement_digest": self.requirement_digest,
                    "error_type": self.error_type,
                    "message": self.message,
                    "diagnostics": self.diagnostics,
                }
            ),
        )


def _generic_authority_gap(
    *,
    stage: str,
    requirement_key: str,
    study: NoetriumUnit,
    exc: BaseException,
) -> ReproductionFleetAuthorityGap:
    return ReproductionFleetAuthorityGap(
        stage=stage,
        requirement_key=requirement_key,
        requirement_digest=canonical_digest(
            {
                "stage": stage,
                "requirement_key": requirement_key,
                "study_definition_digest": study_definition_digest(study),
            }
        ),
        error_type=type(exc).__name__,
        message=str(exc),
    )


def _research_binding_gap(
    study: NoetriumUnit,
    exc: BaseException,
) -> ReproductionFleetAuthorityGap:
    if isinstance(exc, ResearchBindingRequirementMissing):
        return ReproductionFleetAuthorityGap(
            stage=exc.stage,
            requirement_key=exc.requirement_id,
            requirement_digest=exc.requirement_digest,
            error_type=type(exc).__name__,
            message=str(exc),
        )

    if isinstance(exc, ResearchBindingAuthorityError):
        if exc.stage == "participant":
            matches = tuple(
                row
                for row in study.binding_requirements.participants
                if row.role == exc.requirement_id
            )
            requirement_digest = (
                matches[0].requirement_digest
                if len(matches) == 1
                else canonical_digest(
                    {
                        "stage": exc.stage,
                        "requirement_id": exc.requirement_id,
                        "study_definition_digest": study_definition_digest(study),
                    }
                )
            )
        elif exc.stage == "model":
            matches = tuple(
                row
                for row in study.binding_requirements.model_roles
                if row.role == exc.requirement_id
                or row.requirement_id == exc.requirement_id
            )
            requirement_digest = (
                matches[0].requirement_digest
                if len(matches) == 1
                else canonical_digest(
                    {
                        "stage": exc.stage,
                        "requirement_id": exc.requirement_id,
                        "study_definition_digest": study_definition_digest(study),
                    }
                )
            )
        else:
            requirement_digest = canonical_digest(
                {
                    "stage": exc.stage,
                    "requirement_id": exc.requirement_id,
                    "study_definition_digest": study_definition_digest(study),
                }
            )
        return ReproductionFleetAuthorityGap(
            stage=exc.stage,
            requirement_key=exc.requirement_id,
            requirement_digest=requirement_digest,
            error_type=type(exc).__name__,
            message=str(exc),
            diagnostics=tuple(
                row.machine_digest for row in exc.diagnostics
            ),
        )

    manifest = research_project_manifest_requirement(study)
    if isinstance(exc, ResearchManifestRequirementsUnresolved):
        return ReproductionFleetAuthorityGap(
            stage="project_manifest",
            requirement_key=f"{study_project_id(study)}:{study_id(study)}",
            requirement_digest=manifest.requirement_digest,
            error_type=type(exc).__name__,
            message=str(exc),
        )
    return _generic_authority_gap(
        stage="research_binding",
        requirement_key=study_binding_requirement_digest(study),
        study=study,
        exc=exc,
    )


@dataclass(frozen=True, slots=True)
class ReproductionFleetAuthorityLaneAudit:
    """Read-only authority closure result for one materialized fleet lane."""

    package: str
    program_id: str
    graph_node_id: str
    execution_binding_digest: str | None
    research_binding_closed: bool
    study_execution_closed: bool
    reconciliation_closed: bool
    gaps: tuple[ReproductionFleetAuthorityGap, ...]
    blockers: tuple[str, ...]
    audit_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("package", self.package),
            ("program_id", self.program_id),
            ("graph_node_id", self.graph_node_id),
        ):
            if (
                type(value) is not str
                or not value.strip()
                or value != value.strip()
            ):
                raise ValueError(
                    f"fleet authority lane {field_name} must be canonical text"
                )
        if self.execution_binding_digest is not None:
            _require_sha256(
                self.execution_binding_digest,
                "fleet authority lane execution_binding_digest",
            )
        for field_name in (
            "research_binding_closed",
            "study_execution_closed",
            "reconciliation_closed",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise TypeError(
                    f"fleet authority lane {field_name} must be boolean"
                )
        if type(self.gaps) is not tuple or any(
            type(row) is not ReproductionFleetAuthorityGap
            for row in self.gaps
        ):
            raise TypeError(
                "fleet authority lane gaps must be typed immutable tuple"
            )
        if tuple(row.gap_digest for row in self.gaps) != tuple(
            sorted(row.gap_digest for row in self.gaps)
        ):
            raise ValueError(
                "fleet authority lane gaps must be canonical digest order"
            )
        if type(self.blockers) is not tuple or any(
            type(row) is not str or not row
            for row in self.blockers
        ):
            raise TypeError(
                "fleet authority lane blockers must be immutable text tuple"
            )
        object.__setattr__(
            self,
            "audit_digest",
            canonical_digest(
                {
                    "package": self.package,
                    "program_id": self.program_id,
                    "graph_node_id": self.graph_node_id,
                    "execution_binding_digest": self.execution_binding_digest,
                    "research_binding_closed": self.research_binding_closed,
                    "study_execution_closed": self.study_execution_closed,
                    "reconciliation_closed": self.reconciliation_closed,
                    "gaps": tuple(row.gap_digest for row in self.gaps),
                    "blockers": self.blockers,
                }
            ),
        )

    @property
    def execution_authority_closed(self) -> bool:
        return (
            self.research_binding_closed
            and self.study_execution_closed
            and self.reconciliation_closed
            and not self.gaps
            and not self.blockers
        )


@dataclass(frozen=True, slots=True)
class ReproductionFleetAuthorityAudit:
    """Aggregate read-only execution-authority coverage before admission."""

    materialization: ReproductionFleetMaterialization
    authority_manifest_digest: str
    revision_digest: str
    lanes: tuple[ReproductionFleetAuthorityLaneAudit, ...]
    audit_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.materialization) is not ReproductionFleetMaterialization:
            raise TypeError(
                "fleet authority audit requires ReproductionFleetMaterialization"
            )
        _require_sha256(
            self.authority_manifest_digest,
            "fleet authority audit authority_manifest_digest",
        )
        _require_sha256(
            self.revision_digest,
            "fleet authority audit revision_digest",
        )
        if type(self.lanes) is not tuple or not self.lanes:
            raise ValueError("fleet authority audit requires lanes")
        if any(
            type(row) is not ReproductionFleetAuthorityLaneAudit
            for row in self.lanes
        ):
            raise TypeError("fleet authority audit lanes must be typed")
        if tuple(row.program_id for row in self.lanes) != tuple(
            sorted(row.program_id for row in self.lanes)
        ):
            raise ValueError(
                "fleet authority audit lanes must be canonical program order"
            )
        object.__setattr__(
            self,
            "audit_digest",
            canonical_digest(
                {
                    "materialization_digest": (
                        self.materialization.materialization_digest
                    ),
                    "authority_manifest_digest": self.authority_manifest_digest,
                    "revision_digest": self.revision_digest,
                    "lane_audits": tuple(
                        row.audit_digest for row in self.lanes
                    ),
                }
            ),
        )

    @property
    def closed_lane_count(self) -> int:
        return sum(row.execution_authority_closed for row in self.lanes)

    @property
    def blocker_count(self) -> int:
        return sum(len(row.blockers) for row in self.lanes)

    @property
    def gap_count(self) -> int:
        return sum(len(row.gaps) for row in self.lanes)


def audit_materialized_reproduction_fleet_authorities(
    fleet: ReproductionFleetMaterialization,
    *,
    research_bindings: ResearchBindingAuthorityPort,
    experiment_runtime_binding: ResearchExperimentRuntimeBindingAuthority,
    authority_manifest_digest: str,
) -> ReproductionFleetAuthorityAudit:
    """Resolve every lane authority without stores, cuts, tasks, or execution."""

    if type(fleet) is not ReproductionFleetMaterialization:
        raise TypeError(
            "fleet authority audit requires ReproductionFleetMaterialization"
        )
    if not isinstance(research_bindings, ResearchBindingAuthorityPort):
        raise TypeError("fleet authority audit requires research binding authority")
    if (
        type(experiment_runtime_binding)
        is not ResearchExperimentRuntimeBindingAuthority
    ):
        raise TypeError(
            "fleet authority audit requires typed Experiment runtime components"
        )
    _require_sha256(
        authority_manifest_digest,
        "fleet authority audit authority_manifest_digest",
    )

    revision = ResearchGraphRevision(
        fleet.portfolio.unit_id,
        fleet.portfolio.unit_digest,
        (),
        _fleet_revision_message(fleet, authority_manifest_digest)
        + " authority audit",
    )
    graph = compile_research_portfolio_graph(revision, fleet.portfolio)
    experiment_compilation = ReproductionFleetExperimentCompilationProvider(
        fleet,
        research_bindings,
    )
    execution_compiler = ResearchExecutionBindingCompiler(
        experiment_compilation=experiment_compilation,
    )
    lane_by_program = {
        lane.program.unit_id: lane for lane in fleet.lanes
    }
    rows: list[ReproductionFleetAuthorityLaneAudit] = []

    for program_id in sorted(lane_by_program):
        lane = lane_by_program[program_id]
        node = graph.binding(program_id + "::reproduction")
        blockers: list[str] = []
        gaps: list[ReproductionFleetAuthorityGap] = []
        execution_binding = None
        research_closed = False
        study_closed = False
        reconciliation_closed = False

        try:
            execution_binding = execution_compiler.compile_node(
                node,
                graph_id=graph.graph_id,
                graph_digest=graph.graph_digest,
                research_revision_digest=revision.revision_digest,
            )
            research_closed = True
        except BaseException as exc:
            gap = _research_binding_gap(lane.study, exc)
            gaps.append(gap)
            blockers.append(
                "research_binding:"
                + type(exc).__name__
                + ":"
                + str(exc)
            )

        if execution_binding is not None:
            for stage, resolve_stage in (
                (
                    "study_execution",
                    experiment_runtime_binding.resolve_study_execution,
                ),
                (
                    "reconciliation",
                    experiment_runtime_binding.resolve_reconciliation,
                ),
            ):
                try:
                    resolve_stage(execution_binding)
                    if stage == "study_execution":
                        study_closed = True
                    else:
                        reconciliation_closed = True
                except BaseException as exc:
                    if (
                        execution_binding.experiment_definition is None
                        or execution_binding.research_plan is None
                    ):
                        raise RuntimeError(
                            "Experiment binding lost Unit-native compilation"
                        ) from exc
                    study_plan = research_plan_study(
                        execution_binding.research_plan
                    )
                    provider_id = study_plan_provider_id(study_plan)
                    protocol_digest = (
                        research_plan_trial_protocol_identity(
                            execution_binding.research_plan
                        ).unit_digest
                    )
                    requirement_key = (
                        stage
                        + ":"
                        + provider_id
                        + ":"
                        + protocol_digest
                    )
                    requirement_digest = canonical_digest(
                        {
                            "stage": stage,
                            "provider_id": provider_id,
                            "trial_protocol_digest": protocol_digest,
                            "execution_binding_digest": (
                                execution_binding.binding_digest
                            ),
                        }
                    )
                    gaps.append(
                        ReproductionFleetAuthorityGap(
                            stage=stage,
                            requirement_key=requirement_key,
                            requirement_digest=requirement_digest,
                            error_type=type(exc).__name__,
                            message=str(exc),
                        )
                    )
                    blockers.append(
                        stage + ":" + type(exc).__name__ + ":" + str(exc)
                    )

        rows.append(
            ReproductionFleetAuthorityLaneAudit(
                package=lane.definition.package,
                program_id=program_id,
                graph_node_id=node.graph_node_id,
                execution_binding_digest=(
                    None
                    if execution_binding is None
                    else execution_binding.binding_digest
                ),
                research_binding_closed=research_closed,
                study_execution_closed=study_closed,
                reconciliation_closed=reconciliation_closed,
                gaps=tuple(sorted(gaps, key=lambda row: row.gap_digest)),
                blockers=tuple(sorted(set(blockers))),
            )
        )

    return ReproductionFleetAuthorityAudit(
        fleet,
        authority_manifest_digest,
        revision.revision_digest,
        tuple(rows),
    )


def audit_repository_execution_authorities(
    authorities: "ReproductionFleetExecutionAuthorities",
) -> ReproductionFleetAuthorityAudit:
    """Materialize the repository and aggregate all lane-level authority gaps."""

    if type(authorities) is not ReproductionFleetExecutionAuthorities:
        raise TypeError(
            "fleet authority audit requires ReproductionFleetExecutionAuthorities"
        )
    fleet = materialize_repository_execution_fleet(
        authorities.benchmark_resolver,
        capability_resolver=authorities.capability_resolver,
    )
    return audit_materialized_reproduction_fleet_authorities(
        fleet,
        research_bindings=authorities.research_bindings,
        experiment_runtime_binding=authorities.experiment_runtime_binding,
        authority_manifest_digest=authorities.authority_manifest_digest,
    )


@dataclass(frozen=True, slots=True)
class ReproductionFleetPreflightResult:
    """Exact whole-graph admission proof without creating an execution cut."""

    materialization: ReproductionFleetMaterialization
    authority_manifest_digest: str
    execution_id: str
    revision_digest: str
    selected_node_ids: tuple[str, ...]
    admission_digests: tuple[str, ...]
    preflight_digest: str
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.materialization) is not ReproductionFleetMaterialization:
            raise TypeError("fleet preflight requires materialization")
        _require_sha256(
            self.authority_manifest_digest,
            "fleet preflight authority_manifest_digest",
        )
        if type(self.execution_id) is not str or not self.execution_id.strip():
            raise ValueError("fleet preflight execution_id is required")
        _require_sha256(self.revision_digest, "fleet preflight revision")
        _require_sha256(self.preflight_digest, "fleet preflight digest")
        if type(self.selected_node_ids) is not tuple or not self.selected_node_ids:
            raise ValueError("fleet preflight requires selected nodes")
        if tuple(sorted(self.selected_node_ids)) != self.selected_node_ids:
            raise ValueError("fleet preflight selected nodes must be ordered")
        if type(self.admission_digests) is not tuple or any(
            type(value) is not str for value in self.admission_digests
        ):
            raise TypeError("fleet preflight admission digests must be tuple")
        for value in self.admission_digests:
            _require_sha256(value, "fleet preflight admission")
        if len(self.admission_digests) != len(self.selected_node_ids):
            raise ValueError("fleet preflight admission closure is incomplete")
        object.__setattr__(
            self,
            "result_digest",
            canonical_digest(
                {
                    "materialization_digest": self.materialization.materialization_digest,
                    "authority_manifest_digest": self.authority_manifest_digest,
                    "execution_id": self.execution_id,
                    "revision_digest": self.revision_digest,
                    "selected_node_ids": self.selected_node_ids,
                    "admission_digests": self.admission_digests,
                    "preflight_digest": self.preflight_digest,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ReproductionFleetExecutionAuthorities:
    """Complete authority bundle required for one exact fleet execution."""

    benchmark_resolver: ReproductionBenchmarkResolverPort
    research_bindings: ResearchBindingAuthorityPort
    experiment_runtime_binding: ResearchExperimentRuntimeBindingAuthority
    authority_manifest_digest: str
    capability_resolver: ReproductionCapabilityRequirementResolverPort | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.benchmark_resolver,
            ReproductionBenchmarkResolverPort,
        ):
            raise TypeError(
                "fleet execution authorities require benchmark resolver"
            )
        _require_sha256(
            self.benchmark_resolver.authority_digest,
            "fleet execution benchmark authority_digest",
        )
        if not isinstance(
            self.research_bindings,
            ResearchBindingAuthorityPort,
        ):
            raise TypeError(
                "fleet execution authorities require research binding resolver"
            )
        if (
            type(self.experiment_runtime_binding)
            is not ResearchExperimentRuntimeBindingAuthority
        ):
            raise TypeError(
                "fleet execution authorities require typed Experiment runtime components"
            )
        _require_sha256(
            self.authority_manifest_digest,
            "fleet execution authority_manifest_digest",
        )
        if self.capability_resolver is not None and not isinstance(
            self.capability_resolver,
            ReproductionCapabilityRequirementResolverPort,
        ):
            raise TypeError(
                "fleet execution authorities capability resolver must satisfy "
                "ReproductionCapabilityRequirementResolverPort"
            )


class ReproductionFleetExperimentCompilationProvider:
    """Compile reproduction Experiment nodes into canonical Unit-native inputs."""

    def __init__(
        self,
        fleet: ReproductionFleetMaterialization,
        research_bindings: ResearchBindingAuthorityPort,
    ) -> None:
        if type(fleet) is not ReproductionFleetMaterialization:
            raise TypeError(
                "Experiment compilation provider requires materialized fleet"
            )
        if not isinstance(
            research_bindings,
            ResearchBindingAuthorityPort,
        ):
            raise TypeError(
                "Experiment compilation provider requires research binding authority"
            )
        self._research_bindings = research_bindings
        root_id = fleet.portfolio.unit_id
        self._lanes = {
            (root_id, lane.program.unit_id): lane
            for lane in fleet.lanes
        }

    def resolve(
        self,
        node: ResearchExecutionBinding,
    ) -> tuple[
        NoetriumUnit,
        ResearchBindingContribution,
        NoetriumUnit,
        NoetriumUnit,
    ]:
        if type(node) is not ResearchExecutionBinding:
            raise TypeError(
                "Experiment compilation requires compiled graph node"
            )
        lane = self._lanes.get(node.ref.parent_path)
        if lane is None or node.ref.unit_id != "reproduction":
            raise ReproductionResearchCompileError(
                "no materialized fleet lane for graph node "
                f"{node.graph_node_id!r}"
            )
        study = require_study_unit(lane.study)
        closed = self._research_bindings.resolve(study)
        if (
            type(closed) is not tuple
            or len(closed) != 2
            or type(closed[0]) is not ResearchRequirementResolution
            or type(closed[1]) is not ResearchBindingContribution
        ):
            raise TypeError(
                "research binding authority must return "
                "(ResearchRequirementResolution, ResearchBindingContribution)"
            )
        resolution, binding = closed
        if not binding.binding_assurance_complete:
            raise RuntimeError(
                "Study binding assurance is incomplete: "
                + ",".join(
                    row.gap_digest for row in binding.assurance_gaps
                )
            )
        plan = compile_research_plan(study, resolution, binding)
        program = compile_experiment_program(research_plan_study(plan))
        return study, binding, plan, program


__all__ = [
    "ReproductionBenchmarkResolverPort",
    "ReproductionBenchmarkSelection",
    "audit_repository_execution_authorities",
    "audit_materialized_reproduction_fleet_authorities",
    "ReproductionFleetAuthorityGap",
    "ReproductionFleetAuthorityLaneAudit",
    "ReproductionFleetAuthorityAudit",
    "ReproductionFleetExecutionAuthorities",
    "ReproductionFleetExperimentCompilationProvider",
    "ReproductionFleetLane",
    "PartialReproductionFleetMaterialization",
    "ReproductionFleetMaterialization",
    "ReproductionFleetMaterializationBlocker",
    "ReproductionFleetPreflightResult",
    "materialize_repository_execution_fleet",
    "materialize_runnable_repository_execution_fleet",
    "resolve_repository_execution_requests",
    "select_execution_authority_closed_fleet",
]



def select_execution_authority_closed_fleet(
    fleet: ReproductionFleetMaterialization,
    audit: ReproductionFleetAuthorityAudit,
    *,
    portfolio_id: str = "repository-reproductions.runnable-authority-closed",
) -> ReproductionFleetMaterialization | None:
    """Project one materialized fleet onto the lanes whose full authority closes.

    Source/materialization blockers and owner-authority gaps remain in the audit
    report; they never prevent unrelated closed lanes from executing.
    """

    if type(fleet) is not ReproductionFleetMaterialization:
        raise TypeError("authority-closed selection requires fleet materialization")
    if type(audit) is not ReproductionFleetAuthorityAudit:
        raise TypeError("authority-closed selection requires typed authority audit")
    if audit.materialization != fleet:
        raise ValueError("authority-closed selection audit belongs to another fleet")
    closed_program_ids = {
        row.program_id for row in audit.lanes if row.execution_authority_closed
    }
    if not closed_program_ids:
        return None
    lanes = tuple(
        row for row in fleet.lanes if row.program.unit_id in closed_program_ids
    )
    represented_requests = {row.request.request_digest for row in lanes}
    requests = tuple(
        row for row in fleet.requests if row.request_digest in represented_requests
    )
    return ReproductionFleetMaterialization(
        requests,
        lanes,
        compile_bound_reproduction_portfolio(
            portfolio_id,
            tuple(row.binding for row in lanes),
        ),
    )
