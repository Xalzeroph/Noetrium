"""Exact fleet materialization for repository reproductions.

Paper packages own scientific semantics. This module only joins immutable
benchmark authority, typed capability closure and existing Research OS lowering.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from noetrium import api
from noetrium_platform.composition.research_binding_authority import (
    ResearchBindingAuthorityPort,
)
from noetrium_platform.composition.research_os_local import (
    compose_local_research_os,
)
from noetrium_platform.composition.research_os_experiment import (
    ResearchOSExperimentClosure,
    ResearchOSExperimentRuntimeBindingPort,
    compile_research_os_experiment_closure,
)
from noetrium_platform.composition.research_os_graph import CompiledResearchOSGraphNode
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.api import (
    ResearchBindingContribution,
    ResearchRequirementResolution,
)
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkTaskSet,
    ResearchStudyDefinition,
)

from .contracts import ReproductionDefinition
from .research_os import (
    ReproductionCapabilityRequirementResolverPort,
    ReproductionExecutionBinding,
    ReproductionExecutionRequest,
    ReproductionResearchOSCompileError,
    ReproductionStudyFactoryBinding,
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

    benchmark: BenchmarkTaskSet
    benchmark_split_ids: tuple[str, ...]
    resolution_proof_digest: str
    selection_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.benchmark, BenchmarkTaskSet):
            raise TypeError("benchmark selection requires BenchmarkTaskSet")
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
        declared = {row.split_id for row in self.benchmark.splits}
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
                    "benchmark_id": self.benchmark.benchmark_id,
                    "benchmark_revision_id": self.benchmark.revision_id,
                    "benchmark_cut_digest": self.benchmark.cut_digest,
                    "benchmark_split_ids": self.benchmark_split_ids,
                    "resolution_proof_digest": self.resolution_proof_digest,
                }
            ),
        )


@runtime_checkable
class ReproductionBenchmarkResolverPort(Protocol):
    """Resolve exact benchmark cuts/splits from Benchmark + Artifact authority."""

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
    study: ResearchStudyDefinition
    program: api.ResearchProgram
    lane_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.definition) is not ReproductionDefinition:
            raise TypeError("fleet lane requires ReproductionDefinition")
        if type(self.request) is not ReproductionExecutionRequest:
            raise TypeError("fleet lane requires ReproductionExecutionRequest")
        if type(self.binding) is not ReproductionExecutionBinding:
            raise TypeError("fleet lane requires ReproductionExecutionBinding")
        if type(self.study) is not ResearchStudyDefinition:
            raise TypeError("fleet lane requires ResearchStudyDefinition")
        if type(self.program) is not api.ResearchProgram:
            raise TypeError("fleet lane requires ResearchProgram")
        if (
            self.definition.package != self.request.package
            or self.definition.package != self.binding.package
        ):
            raise ValueError("fleet lane package identity drifted")
        if self.binding.study_factory != self.request.study_factory:
            raise ValueError("fleet lane Study factory drifted")
        if self.binding.benchmark_id != self.request.benchmark.benchmark_id:
            raise ValueError("fleet lane benchmark identity drifted")
        if self.study.benchmark.cut_digest != self.request.benchmark.cut_digest:
            raise ValueError("fleet lane Study benchmark cut drifted")
        if self.study.benchmark_split_id != self.binding.benchmark_split_id:
            raise ValueError("fleet lane Study split identity drifted")
        expected_program_id = (
            f"{self.definition.package}.{self.binding.binding_id}"
        )
        if self.program.program_id != expected_program_id:
            raise ValueError("fleet lane ResearchProgram identity drifted")
        object.__setattr__(
            self,
            "lane_digest",
            canonical_digest(
                {
                    "definition_digest": self.definition.definition_digest,
                    "request_digest": self.request.request_digest,
                    "binding_digest": self.binding.binding_digest,
                    "study_definition_digest": self.study.definition_digest,
                    "program_digest": self.program.program_digest,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ReproductionFleetMaterialization:
    requests: tuple[ReproductionExecutionRequest, ...]
    lanes: tuple[ReproductionFleetLane, ...]
    portfolio: api.ResearchPortfolio
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
        if type(self.portfolio) is not api.ResearchPortfolio:
            raise TypeError("fleet materialization requires ResearchPortfolio")

        request_digests = tuple(row.request_digest for row in self.requests)
        lane_digests = tuple(row.lane_digest for row in self.lanes)
        if len(request_digests) != len(set(request_digests)):
            raise ValueError("fleet requests must be unique")
        if len(lane_digests) != len(set(lane_digests)):
            raise ValueError("fleet lanes must be unique")

        program_ids = tuple(row.program.program_id for row in self.lanes)
        if program_ids != tuple(sorted(program_ids)):
            raise ValueError("fleet lanes must be canonically ordered")
        if len(program_ids) != len(set(program_ids)):
            raise ValueError("fleet ResearchProgram identities must be unique")
        if tuple(row.program_id for row in self.portfolio.programs) != program_ids:
            raise ValueError("fleet portfolio drifted from materialized lanes")

        object.__setattr__(
            self,
            "materialization_digest",
            canonical_digest(
                {
                    "request_digests": request_digests,
                    "lane_digests": lane_digests,
                    "portfolio_digest": self.portfolio.portfolio_digest,
                }
            ),
        )


def resolve_repository_execution_requests(
    benchmark_resolver: ReproductionBenchmarkResolverPort,
) -> tuple[ReproductionExecutionRequest, ...]:
    """Discover every executable reproduction and close its benchmark authority."""

    if not isinstance(benchmark_resolver, ReproductionBenchmarkResolverPort):
        raise TypeError("fleet requires ReproductionBenchmarkResolverPort")

    requests: list[ReproductionExecutionRequest] = []
    for definition in executable_reproduction_definitions():
        factories = resolve_study_factory_bindings(definition)
        split_consumers = set(resolve_benchmark_split_consumers(definition))
        method_split_axis = any(
            consumer.startswith("method:")
            for consumer in split_consumers
        )
        covered_benchmarks: set[str] = set()

        for factory in factories:
            selections = benchmark_resolver.resolve(definition, factory)
            if type(selections) is not tuple or not selections:
                raise ReproductionResearchOSCompileError(
                    f"{definition.package} Study {factory.qualname} has no "
                    "exact benchmark selection"
                )
            if any(type(row) is not ReproductionBenchmarkSelection for row in selections):
                raise TypeError(
                    f"{definition.package} benchmark resolver returned "
                    "untyped selection"
                )
            selection_digests = tuple(row.selection_digest for row in selections)
            if len(selection_digests) != len(set(selection_digests)):
                raise ReproductionResearchOSCompileError(
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
                benchmark_id = selection.benchmark.benchmark_id
                if benchmark_id not in definition.catalog.benchmark_ids:
                    raise ReproductionResearchOSCompileError(
                        f"{definition.package} benchmark authority returned "
                        f"out-of-catalog benchmark {benchmark_id!r}"
                    )
                if split_aware and not selection.benchmark_split_ids:
                    raise ReproductionResearchOSCompileError(
                        f"{definition.package} Study {factory.qualname} "
                        "requires explicit benchmark split selection"
                    )
                if not split_aware and selection.benchmark_split_ids:
                    raise ReproductionResearchOSCompileError(
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
                covered_benchmarks.add(benchmark_id)

        missing = tuple(
            sorted(set(definition.catalog.benchmark_ids) - covered_benchmarks)
        )
        if missing:
            raise ReproductionResearchOSCompileError(
                f"{definition.package} benchmark authority did not close "
                f"catalog benchmarks: {missing}"
            )

    ordered = tuple(
        sorted(
            requests,
            key=lambda row: (
                row.package,
                row.study_factory,
                row.benchmark.benchmark_id,
                row.benchmark.revision_id,
                row.benchmark.cut_digest,
                row.benchmark_split_ids,
                row.benchmark_resolution_proof_digest,
            ),
        )
    )
    digests = tuple(row.request_digest for row in ordered)
    if len(digests) != len(set(digests)):
        raise ReproductionResearchOSCompileError(
            "fleet execution request identities must be unique"
        )
    return ordered


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
            raise ReproductionResearchOSCompileError(
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
        sorted(lanes, key=lambda row: row.program.program_id)
    )
    portfolio = api.ResearchPortfolio(
        portfolio_id,
        tuple(row.program for row in ordered_lanes),
    )
    return ReproductionFleetMaterialization(
        requests,
        ordered_lanes,
        portfolio,
    )


def execute_materialized_reproduction_fleet(
    fleet: ReproductionFleetMaterialization,
    *,
    state_root: Path,
    research_bindings: ResearchBindingAuthorityPort,
    experiment_bindings: ResearchOSExperimentRuntimeBindingPort,
    execution_id: str | None = None,
):
    """Commit and RUN one fully materialized fleet through canonical Research OS.

    Durable stores, graph control, resource pool, value authority, Machine
    journals and Experimentation runtime all come from the platform's single
    local Research OS composition. No reproduction-owned launcher exists.
    """

    if type(fleet) is not ReproductionFleetMaterialization:
        raise TypeError("fleet execution requires ReproductionFleetMaterialization")
    if type(state_root) is not Path:
        raise TypeError("fleet execution state_root must be pathlib.Path")
    if not isinstance(
        research_bindings,
        ResearchBindingAuthorityPort,
    ):
        raise TypeError("fleet execution requires research binding resolver")
    if not isinstance(
        experiment_bindings,
        ResearchOSExperimentRuntimeBindingPort,
    ):
        raise TypeError("fleet execution requires experiment runtime binding resolver")
    if execution_id is None:
        execution_id = (
            "repository-reproductions."
            + fleet.materialization_digest[:24]
        )
    if (
        type(execution_id) is not str
        or not execution_id.strip()
        or execution_id != execution_id.strip()
    ):
        raise ValueError("fleet execution_id must be canonical non-empty text")

    closures = ReproductionFleetExperimentClosureProvider(
        fleet,
        research_bindings,
    )
    composition = compose_local_research_os(
        state_root,
        experiment_closures=closures,
        experiment_bindings=experiment_bindings,
    )
    try:
        revision = composition.research_os.commit(
            fleet.portfolio,
            message=(
                "repository reproduction fleet "
                + fleet.materialization_digest
            ),
        )
        target = api.ResearchExecutionTarget(execution_id, revision)
        return composition.research_os.run(target)
    finally:
        composition.close()


@dataclass(frozen=True, slots=True)
class ReproductionFleetExecutionAuthorities:
    """Complete authority bundle required for one exact fleet execution."""

    benchmark_resolver: ReproductionBenchmarkResolverPort
    research_bindings: ResearchBindingAuthorityPort
    experiment_bindings: ResearchOSExperimentRuntimeBindingPort
    capability_resolver: ReproductionCapabilityRequirementResolverPort | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.benchmark_resolver,
            ReproductionBenchmarkResolverPort,
        ):
            raise TypeError(
                "fleet execution authorities require benchmark resolver"
            )
        if not isinstance(
            self.research_bindings,
            ResearchBindingAuthorityPort,
        ):
            raise TypeError(
                "fleet execution authorities require research binding resolver"
            )
        if not isinstance(
            self.experiment_bindings,
            ResearchOSExperimentRuntimeBindingPort,
        ):
            raise TypeError(
                "fleet execution authorities require experiment runtime binding resolver"
            )
        if self.capability_resolver is not None and not isinstance(
            self.capability_resolver,
            ReproductionCapabilityRequirementResolverPort,
        ):
            raise TypeError(
                "fleet execution authorities capability resolver must satisfy "
                "ReproductionCapabilityRequirementResolverPort"
            )


@dataclass(frozen=True, slots=True)
class ReproductionFleetExecutionResult:
    """Materialization + canonical Research OS control receipt."""

    materialization: ReproductionFleetMaterialization
    receipt: api.ResearchControlReceipt
    execution_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.materialization) is not ReproductionFleetMaterialization:
            raise TypeError(
                "fleet execution result requires ReproductionFleetMaterialization"
            )
        if type(self.receipt) is not api.ResearchControlReceipt:
            raise TypeError(
                "fleet execution result requires ResearchControlReceipt"
            )
        object.__setattr__(
            self,
            "execution_digest",
            canonical_digest(
                {
                    "materialization_digest": (
                        self.materialization.materialization_digest
                    ),
                    "receipt_digest": self.receipt.receipt_digest,
                    "execution_id": self.receipt.target.execution_id,
                    "revision_digest": (
                        self.receipt.target.research_revision_digest
                    ),
                    "state": self.receipt.state,
                }
            ),
        )


def run_repository_execution_fleet(
    authorities: ReproductionFleetExecutionAuthorities,
    *,
    state_root: Path,
    execution_id: str | None = None,
) -> ReproductionFleetExecutionResult:
    """discover -> resolve -> materialize -> compile -> commit -> RUN.

    This function is the single repository fleet execution composition path.
    It delegates whole-graph preflight, resource admission, durable cut creation,
    scheduling, checkpointing, recovery semantics and evidence to Research OS.
    """

    if type(authorities) is not ReproductionFleetExecutionAuthorities:
        raise TypeError(
            "fleet run requires ReproductionFleetExecutionAuthorities"
        )
    fleet = materialize_repository_execution_fleet(
        authorities.benchmark_resolver,
        capability_resolver=authorities.capability_resolver,
    )
    receipt = execute_materialized_reproduction_fleet(
        fleet,
        state_root=state_root,
        research_bindings=authorities.research_bindings,
        experiment_bindings=authorities.experiment_bindings,
        execution_id=execution_id,
    )
    return ReproductionFleetExecutionResult(fleet, receipt)


class ReproductionFleetExperimentClosureProvider:
    """Bridge materialized reproduction lanes into canonical ExperimentClosure."""

    def __init__(
        self,
        fleet: ReproductionFleetMaterialization,
        research_bindings: ResearchBindingAuthorityPort,
    ) -> None:
        if type(fleet) is not ReproductionFleetMaterialization:
            raise TypeError("closure provider requires materialized fleet")
        if not isinstance(
            research_bindings,
            ResearchBindingAuthorityPort,
        ):
            raise TypeError("closure provider requires research binding resolver")
        self._research_bindings = research_bindings
        self._lanes = {
            lane.program.program_id: lane
            for lane in fleet.lanes
        }

    def resolve(
        self,
        *,
        graph_id: str,
        graph_digest: str,
        research_revision_digest: str,
        node: CompiledResearchOSGraphNode,
    ) -> ResearchOSExperimentClosure:
        if type(node) is not CompiledResearchOSGraphNode:
            raise TypeError("ExperimentClosure requires compiled graph node")
        lane = self._lanes.get(node.ref.program_id)
        if lane is None or node.ref.node_id != "reproduction":
            raise ReproductionResearchOSCompileError(
                f"no materialized fleet lane for graph node "
                f"{node.graph_node_id!r}"
            )
        closed = self._research_bindings.resolve(lane.study)
        if (
            type(closed) is not tuple
            or len(closed) != 2
            or type(closed[0]) is not ResearchRequirementResolution
            or type(closed[1]) is not ResearchBindingContribution
        ):
            raise TypeError(
                "research binding resolver must return "
                "(ResearchRequirementResolution, ResearchBindingContribution)"
            )
        resolution, binding = closed
        return compile_research_os_experiment_closure(
            graph_id=graph_id,
            graph_digest=graph_digest,
            research_revision_digest=research_revision_digest,
            node=node,
            definition=lane.study,
            resolution=resolution,
            binding=binding,
        )


__all__ = [
    "ReproductionBenchmarkResolverPort",
    "ReproductionBenchmarkSelection",
    "ReproductionFleetExecutionAuthorities",
    "ReproductionFleetExecutionResult",
    "ReproductionFleetExperimentClosureProvider",
    "ReproductionFleetLane",
    "ReproductionFleetMaterialization",
    "execute_materialized_reproduction_fleet",
    "materialize_repository_execution_fleet",
    "resolve_repository_execution_requests",
    "run_repository_execution_fleet",
]
