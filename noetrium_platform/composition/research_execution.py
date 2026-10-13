from __future__ import annotations

from dataclasses import dataclass, field, replace
import time
from threading import RLock
from typing import Protocol, runtime_checkable

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.evidence.artifact.contracts import ArtifactContentIdentity
from noetrium_platform.evidence.observability.api import DiagnosticDegradationPort
from noetrium_platform.foundation.kernel.kernel import (
    CostObservationSinkPort,
    RuntimeCostScope,
    ExecutionContext,
    GraphExecutionCoordinate,
    execution_context_scope,
    JsonObject,
    JsonValue,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.foundation.kernel.kernel.errors import attempt_secondary_delivery
from noetrium_platform.evidence.artifact.lineage.relation.api import (
    ArtifactLineageEdge,
    ArtifactLineageRelationPort,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskContextPort,
    TaskFailureScope,
)
from noetrium_platform.infrastructure.lifecycle.runtime import ResourceLifetimeController
from noetrium_platform.infrastructure.reliability.failure.api import (
    DEFAULT_FAILURE_CATALOG,
    FailureMaterializationPort,
    FailureReference,
    exception_failure_id,
)
from noetrium_platform.product.research_control import (
    ResearchControlAction,
    ResearchControlReceipt,
    ResearchControlRequest,
    ResearchExecutionTarget,
    ResearchGraphRevision,
)
from noetrium_platform.foundation.kernel.structure import GraphStorageKind, NoetriumUnit
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphActiveCutStorePort,
    ResearchGraphAttemptState,
    ResearchGraphControlPhase,
    ResearchGraphControlStorePort,
    ResearchGraphCutSwitchFence,
    ResearchGraphExecutionConflict,
    ResearchGraphExecutionReport,
    ResearchGraphExecutionStorePort,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeControlPhase,
    ResearchGraphNodeControlStorePort,
    ResearchGraphOwnerGenerationRecoveryPort,
    ResearchGraphReconciliationDisposition,
)

from .diagnostic_degradation import record_diagnostic_degradation
from .research_control import ResearchExecutionControlPort
from .research_checkpoint import (
    ResearchGraphCheckpoint,
    ResearchGraphCheckpointStorePort,
    ResearchNodeCheckpointPort,
    ResearchNodeCheckpointProof,
)
from .research_symbol_authority import ResearchSymbolBindingAuthorityPort
from .research_experiment import ResearchExperimentCompilationPort
from .research_graph import ResearchGraphControlHalt, ResearchGraphNodeControlHalt
from .research_execution_graph import (
    ResearchCompilationView,
    ResearchExecutionBinding,
    bind_research_portfolio_scheduler,
    compile_research_portfolio_graph,
)
from .research_lowering import (
    ResearchGraphExecutionBinding,
    compile_research_execution_bindings,
    research_execution_bindings_digest,
)
from .research_reconciliation import (
    ResearchNodeReconciliationPort,
    ResearchNodeReconciliationProof,
)
from .research_execution_migration import (
    ResearchExecutionActivation,
    ResearchExecutionCut,
    ResearchExecutionMigrationDecision,
    ResearchReuseMaterializerPort,
    ResearchReuseProof,
    activate_research_execution_cut,
    materialize_research_execution_migration,
    plan_research_execution_migration,
)
from .research_values import (
    ResearchValueReference,
    ResearchValueRouter,
    ResearchValueSubject,
    lookup_research_node_input_references,
    publish_research_node_outputs,
    validate_research_value_authorities,
)


def _same_compilation_identity(
    left: ResearchCompilationView,
    right: ResearchCompilationView,
) -> bool:
    """Compare stable execution identity, never ephemeral compilation indexes."""
    if type(left) is not ResearchCompilationView or type(right) is not ResearchCompilationView:
        return False
    return (
        left.graph_id == right.graph_id
        and left.graph_digest == right.graph_digest
        and left.research_revision_digest == right.research_revision_digest
    )


@dataclass(frozen=True, slots=True)
class ResearchNodeAdmission:
    """Exact runtime admission for one immutable bound NoetriumUnit node."""

    graph_node_id: str
    semantic_digest: str
    binding_digest: str
    runtime_binding_digest: str
    admission_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.graph_node_id) is not str
            or not self.graph_node_id.strip()
            or self.graph_node_id != self.graph_node_id.strip()
        ):
            raise ValueError("research node admission graph_node_id is required")
        require_sha256(
            self.semantic_digest,
            "research node admission semantic_digest",
        )
        require_sha256(
            self.binding_digest,
            "research node admission binding_digest",
        )
        require_sha256(
            self.runtime_binding_digest,
            "research node admission runtime_binding_digest",
        )
        object.__setattr__(
            self,
            "admission_digest",
            canonical_digest(
                {
                    "graph_node_id": self.graph_node_id,
                    "semantic_digest": self.semantic_digest,
                    "binding_digest": self.binding_digest,
                    "runtime_binding_digest": self.runtime_binding_digest,
                }
            ),
        )


@runtime_checkable
class ResearchNodeRuntimePort(Protocol):
    """Internal L2->L3 runtime boundary; downstream authors never implement this."""

    def admit(
        self,
        node: ResearchExecutionBinding,
        binding: ResearchGraphExecutionBinding,
    ) -> ResearchNodeAdmission: ...

    def execute(
        self,
        context: ExecutionContext,
        task_context: TaskContextPort,
        node: ResearchExecutionBinding,
        binding: ResearchGraphExecutionBinding,
        inputs: JsonObject,
        *,
        execution_cut_id: str,
        deadline: Deadline | None,
    ) -> JsonValue: ...


@runtime_checkable
class ResearchPortfolioRuntimePort(Protocol):
    """Optional portfolio-scoped runtime composition before node admission."""

    def bind_portfolio(self, compilation: ResearchCompilationView) -> None: ...


@dataclass(frozen=True, slots=True)
class PreparedResearchExecution:
    target: ResearchExecutionTarget
    compilation: ResearchCompilationView
    bindings: tuple[ResearchGraphExecutionBinding, ...]
    cut: ResearchExecutionCut
    selected_node_ids: tuple[str, ...]
    admissions: tuple[ResearchNodeAdmission, ...]
    bindings_digest: str = field(init=False)
    selection_digest: str = field(init=False)
    preflight_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.target) is not ResearchExecutionTarget:
            raise TypeError("prepared research execution target must be typed")
        if type(self.compilation) is not ResearchCompilationView:
            raise TypeError("prepared research execution compilation must be typed")
        if type(self.bindings) is not tuple or not self.bindings or any(
            type(row) is not ResearchGraphExecutionBinding for row in self.bindings
        ):
            raise TypeError("prepared research execution bindings must be non-empty typed tuple")
        if type(self.cut) is not ResearchExecutionCut:
            raise TypeError("prepared research execution cut must be typed")
        if type(self.selected_node_ids) is not tuple or not self.selected_node_ids or any(
            type(node_id) is not str or not node_id.strip()
            for node_id in self.selected_node_ids
        ):
            raise TypeError(
                "prepared research execution selection must be a non-empty text tuple"
            )
        selected = tuple(sorted(self.selected_node_ids))
        if len(selected) != len(set(selected)):
            raise ValueError("prepared research execution selection must be unique")
        compiled_selected: dict[str, ResearchExecutionBinding] = {}
        unknown: list[str] = []
        for node_id in selected:
            try:
                compiled_selected[node_id] = self.compilation.binding(node_id)
            except KeyError:
                unknown.append(node_id)
        if unknown:
            raise ValueError(
                "prepared research execution selection has unknown nodes: "
                f"{tuple(unknown)}"
            )
        if type(self.admissions) is not tuple or any(
            type(row) is not ResearchNodeAdmission
            for row in self.admissions
        ):
            raise TypeError("prepared research execution admissions must be typed")

        ordered = tuple(
            sorted(self.admissions, key=lambda row: row.graph_node_id)
        )
        admission_ids = tuple(row.graph_node_id for row in ordered)
        if admission_ids != selected:
            raise ValueError(
                "prepared research execution admission closure does not match selection"
            )
        if self.compilation.revision != self.target.revision:
            raise ValueError("prepared research execution revision drifted")
        if self.cut.execution_id != self.target.execution_id:
            raise ValueError("prepared research execution logical identity drifted")
        if self.cut.graph_digest != self.compilation.graph_digest:
            raise ValueError("prepared research execution cut graph drifted")
        if (
            self.cut.research_revision_digest
            != self.target.research_revision_digest
        ):
            raise ValueError("prepared research execution cut revision drifted")

        by_id = compiled_selected
        bindings = {
            row.graph_node_id: row
            for row in self.bindings
        }
        if tuple(sorted(bindings)) != selected:
            raise ValueError(
                "prepared research execution binding closure does not match selection"
            )
        for admission in ordered:
            compiled = by_id[admission.graph_node_id]
            binding = bindings[admission.graph_node_id]
            if admission.semantic_digest != compiled.semantic_digest:
                raise ValueError("research node admission semantic identity drifted")
            binding.validate_source(compiled)
            if admission.binding_digest != binding.binding_digest:
                raise ValueError("research node admission binding identity drifted")

        ordered_bindings = tuple(
            sorted(self.bindings, key=lambda row: row.graph_node_id)
        )
        object.__setattr__(self, "bindings", ordered_bindings)
        bindings_digest = research_execution_bindings_digest(
            self.compilation,
            ordered_bindings,
        )
        object.__setattr__(self, "bindings_digest", bindings_digest)
        object.__setattr__(self, "selected_node_ids", selected)
        object.__setattr__(self, "admissions", ordered)
        selection_digest = canonical_digest(
            {
                "graph_digest": self.compilation.graph_digest,
                "research_revision_digest": self.target.research_revision_digest,
                "selected_node_ids": selected,
            }
        )
        object.__setattr__(self, "selection_digest", selection_digest)
        object.__setattr__(
            self,
            "preflight_digest",
            canonical_digest(
                {
                    "target_digest": self.target.target_digest,
                    "graph_digest": self.compilation.graph_digest,
                    "bindings_digest": bindings_digest,
                    "cut_id": self.cut.cut_id,
                    "selection_digest": selection_digest,
                    "admissions": tuple(
                        row.admission_digest
                        for row in ordered
                    ),
                }
            ),
        )

    def admission(
        self,
        graph_node_id: str,
    ) -> ResearchNodeAdmission:
        for row in self.admissions:
            if row.graph_node_id == graph_node_id:
                return row
        raise KeyError(graph_node_id)


    def binding(
        self,
        graph_node_id: str,
    ) -> ResearchGraphExecutionBinding:
        for row in self.bindings:
            if row.graph_node_id == graph_node_id:
                return row
        raise KeyError(graph_node_id)


class ResearchExecutionUnsupported(RuntimeError):
    pass


class ExecutionNodeFailure(RuntimeError):
    """Graph-node boundary wrapper over the authoritative Failure Unit ref."""

    def __init__(self, failure_reference: FailureReference) -> None:
        if not isinstance(failure_reference, FailureReference):
            raise TypeError(
                "execution node failure requires typed FailureReference"
            )
        self.failure_reference = failure_reference
        self.failure_id = failure_reference.failure_id
        self.evidence_refs = failure_reference.graph_evidence_refs
        self.request_refs = failure_reference.request_refs
        self.effect_refs = failure_reference.effect_refs
        self.state_refs = failure_reference.state_refs
        self.correlation_refs = failure_reference.correlation_refs
        super().__init__(
            "execution projection node failed; "
            f"failure_id={self.failure_id}"
        )

    @property
    def failure_correlation_refs(self) -> tuple[str, ...]:
        return self.failure_reference.lower_refs


def _dependency_closed_selection_node_ids(
    compilation: ResearchCompilationView,
    seed_node_ids: tuple[str, ...],
) -> tuple[str, ...]:
    if type(compilation) is not ResearchCompilationView:
        raise TypeError("research execution selection requires compiled graph")
    if type(seed_node_ids) is not tuple or not seed_node_ids or any(
        type(node_id) is not str or not node_id.strip()
        for node_id in seed_node_ids
    ):
        raise TypeError(
            "research execution selection seeds must be a non-empty text tuple"
        )
    seeds = tuple(sorted(seed_node_ids))
    if len(seeds) != len(set(seeds)):
        raise ValueError("research execution selection seeds must be unique")
    unknown: list[str] = []
    for node_id in seeds:
        try:
            compilation.binding(node_id)
        except KeyError:
            unknown.append(node_id)
    if unknown:
        raise ResearchExecutionUnsupported(
            "research execution selection references unknown nodes: "
            f"{tuple(unknown)}"
        )

    selected: set[str] = set()
    pending = list(reversed(seeds))
    while pending:
        node_id = pending.pop()
        if node_id in selected:
            continue
        selected.add(node_id)
        dependencies = compilation.binding(node_id).depends_on_node_ids
        pending.extend(
            dependency
            for dependency in reversed(dependencies)
            if dependency not in selected
        )
    return tuple(sorted(selected))


def _execution_selection_node_ids(
    compilation: ResearchCompilationView,
    target: ResearchExecutionTarget,
) -> tuple[str, ...]:
    if type(target) is not ResearchExecutionTarget:
        raise TypeError("research execution selection requires typed target")
    if target.graph is None:
        return tuple(node.graph_node_id for node in compilation.bindings)
    try:
        node = compilation.binding_by_ref(target.graph)
    except KeyError as exc:
        raise ResearchExecutionUnsupported(
            "node-scoped RUN target does not identify exactly one NoetriumUnit node"
        ) from exc
    return _dependency_closed_selection_node_ids(
        compilation,
        (node.graph_node_id,),
    )


def prepare_research_execution(
    target: ResearchExecutionTarget,
    portfolio: NoetriumUnit,
    runtime: ResearchNodeRuntimePort,
    values: ResearchValueRouter,
    *,
    experiment_compilation: ResearchExperimentCompilationPort | None = None,
    symbol_bindings: ResearchSymbolBindingAuthorityPort | None = None,
    artifact_lineage: ArtifactLineageRelationPort | None = None,
    selection_seed_node_ids: tuple[str, ...] | None = None,
    cut_generation: int = 1,
) -> PreparedResearchExecution:
    """Close the complete execution dependency set before any durable cut exists."""

    if type(target) is not ResearchExecutionTarget:
        raise TypeError("research execution preflight target must be typed")
    if type(portfolio) is not NoetriumUnit:
        raise TypeError("research execution preflight portfolio must be typed")
    if portfolio.unit_id != target.portfolio_id:
        raise ValueError("research execution portfolio identity drifted")
    if portfolio.unit_digest != target.revision.portfolio_digest:
        raise ValueError("research execution portfolio digest drifted")
    if not isinstance(runtime, ResearchNodeRuntimePort):
        raise TypeError("research execution runtime must satisfy ResearchNodeRuntimePort")
    if type(values) is not ResearchValueRouter:
        raise TypeError("research execution values must be ResearchValueRouter")

    compilation = compile_research_portfolio_graph(
        target.revision,
        portfolio,
    )
    if isinstance(runtime, ResearchPortfolioRuntimePort):
        runtime.bind_portfolio(compilation)
    if selection_seed_node_ids is None:
        selected_node_ids = _execution_selection_node_ids(compilation, target)
    else:
        if target.graph is not None:
            raise ValueError(
                "explicit research execution selection seeds require a whole-graph target"
            )
        selected_node_ids = _dependency_closed_selection_node_ids(
            compilation,
            selection_seed_node_ids,
        )
    bindings = compile_research_execution_bindings(
        compilation,
        experiment_compilation=experiment_compilation,
        symbol_bindings=symbol_bindings,
        selected_node_ids=selected_node_ids,
    )
    validate_research_value_authorities(
        compilation,
        values,
        selected_node_ids=selected_node_ids,
    )
    requires_artifact_lineage = any(
        output.type_ref.storage_kind is GraphStorageKind.ARTIFACT
        and any(
            edge.target_port is not None
            and edge.storage_kind is GraphStorageKind.ARTIFACT
            for edge in node.incoming_edges
        )
        for node in (
            compilation.binding(node_id)
            for node_id in selected_node_ids
        )
        for output in node.graph.boundary.outputs
    )
    if requires_artifact_lineage and artifact_lineage is None:
        raise ResearchExecutionUnsupported(
            "derived ARTIFACT outputs require ArtifactLineageRelationPort"
        )
    if artifact_lineage is not None and not isinstance(
        artifact_lineage,
        ArtifactLineageRelationPort,
    ):
        raise TypeError(
            "research execution artifact_lineage must satisfy "
            "ArtifactLineageRelationPort"
        )

    bound = {
        row.graph_node_id: row
        for row in bindings
    }
    admissions: list[ResearchNodeAdmission] = []
    for node_id in selected_node_ids:
        node = compilation.binding(node_id)
        admission = runtime.admit(node, bound[node.graph_node_id])
        if type(admission) is not ResearchNodeAdmission:
            raise TypeError("research runtime returned invalid node admission")
        if admission.graph_node_id != node.graph_node_id:
            raise ValueError("research runtime admission node identity drifted")
        admissions.append(admission)

    cut = ResearchExecutionCut.from_compilation(
        target.execution_id,
        compilation,
        generation=cut_generation,
    )
    return PreparedResearchExecution(
        target,
        compilation,
        bindings,
        cut,
        selected_node_ids,
        tuple(admissions),
    )


class PreparedResearchNodeExecutor:
    """Scheduler adapter over a preflight-closed runtime/value binding."""

    def __init__(
        self,
        prepared: PreparedResearchExecution,
        runtime: ResearchNodeRuntimePort,
        values: ResearchValueRouter,
        *,
        experiment_compilation: ResearchExperimentCompilationPort | None = None,
        artifact_lineage: ArtifactLineageRelationPort | None = None,
        cost_observation: CostObservationSinkPort | None = None,
        diagnostic_degradation: DiagnosticDegradationPort | None = None,
        failure_materializer: FailureMaterializationPort | None = None,
        lifetime_controller: ResourceLifetimeController | None = None,
        causal_event_refs: tuple[str, ...] = (),
    ) -> None:
        if type(prepared) is not PreparedResearchExecution:
            raise TypeError("research node executor requires prepared execution")
        if not isinstance(runtime, ResearchNodeRuntimePort):
            raise TypeError("research node executor runtime must satisfy typed port")
        if type(values) is not ResearchValueRouter:
            raise TypeError("research node executor values must be typed router")
        self._prepared = prepared
        self._runtime = runtime
        self._values = values
        if experiment_compilation is not None and not isinstance(
            experiment_compilation,
            ResearchExperimentCompilationPort,
        ):
            raise TypeError(
                "Research execution control experiment_compilation must satisfy "
                "ResearchExperimentCompilationPort"
            )
        self._experiment_compilation = experiment_compilation
        if artifact_lineage is not None and not isinstance(
            artifact_lineage,
            ArtifactLineageRelationPort,
        ):
            raise TypeError(
                "research node executor artifact_lineage must satisfy "
                "ArtifactLineageRelationPort"
            )
        self._artifact_lineage = artifact_lineage
        if cost_observation is not None and not isinstance(
            cost_observation, CostObservationSinkPort
        ):
            raise TypeError("research node executor cost_observation must satisfy typed port")
        if diagnostic_degradation is not None and not isinstance(
            diagnostic_degradation, DiagnosticDegradationPort
        ):
            raise TypeError(
                "research node executor diagnostic_degradation must satisfy typed port"
            )
        self._cost_observation = cost_observation
        self._diagnostic_degradation = diagnostic_degradation
        if failure_materializer is not None and not isinstance(
            failure_materializer, FailureMaterializationPort
        ):
            raise TypeError(
                "research node failure_materializer must satisfy typed port"
            )
        self._failure_materializer = failure_materializer
        self._causal_event_refs = causal_event_refs
        if lifetime_controller is not None and not isinstance(
            lifetime_controller, ResourceLifetimeController
        ):
            raise TypeError("research node executor lifetime_controller must be typed")
        self._lifetime_controller = lifetime_controller
        self._bindings = {
            row.graph_node_id: row
            for row in prepared.bindings
        }

    def execute(
        self,
        task_context: TaskContextPort,
        node: ResearchExecutionBinding,
        *,
        deadline: Deadline | None,
    ) -> None:
        if type(node) is not ResearchExecutionBinding:
            raise TypeError("research node executor requires compiled graph node")
        admission = self._prepared.admission(node.graph_node_id)
        binding = self._bindings[node.graph_node_id]
        if admission.semantic_digest != node.semantic_digest:
            raise ValueError("research node execution semantic admission drifted")
        if admission.binding_digest != binding.binding_digest:
            raise ValueError("research node execution binding admission drifted")

        task_context.checkpoint()
        execution_attempt_id = canonical_digest(
            {
                "schema": "noetrium.research-node-attempt.v1",
                "execution_cut_id": self._prepared.cut.cut_id,
                "graph_node_id": node.graph_node_id,
                "attempt_id": task_context.task_id,
            }
        )
        scientific_context = ExecutionContext(
            run_id=execution_attempt_id,
            trace_id=canonical_digest(
                {
                    "execution_cut_id": self._prepared.cut.cut_id,
                    "graph_digest": self._prepared.compilation.graph_digest,
                }
            ),
            span_id=node.graph_node_id,
            task_id=task_context.task_id,
            component_id=node.graph_node_id,
            execution_tenant_id=self._prepared.target.portfolio_id,
            causal_event_refs=self._causal_event_refs,
            graph_coordinate=GraphExecutionCoordinate(
                research_revision_digest=self._prepared.cut.research_revision_digest,
                execution_id=self._prepared.cut.execution_id,
                cut_id=self._prepared.cut.cut_id,
                graph_path=node.ref.path,
                graph_node_id=node.graph_node_id,
                attempt_id=task_context.task_id,
                generation=self._prepared.cut.generation,
            ),
        )
        input_references = lookup_research_node_input_references(
            self._prepared.cut.cut_id,
            self._prepared.compilation,
            node,
            self._values,
        )
        inputs: JsonObject = {
            input_name: self._values.resolve(reference)
            for input_name, reference in input_references.items()
        }
        lifetime_lease = (
            None
            if self._lifetime_controller is None
            else self._lifetime_controller.acquire(
                (
                    "graph-attempt:"
                    + self._prepared.cut.cut_id
                    + ":"
                    + node.graph_node_id
                    + ":"
                    + task_context.task_id
                )
            )
        )
        cost_scope = RuntimeCostScope(
            scientific_context,
            algorithm_id="research.execution.node.attempt.total",
            implementation_digest=admission.runtime_binding_digest,
        )
        try:
            with execution_context_scope(scientific_context), cost_scope:
                cost_scope.set_scale("input_count", len(inputs))
                cost_scope.set_scale(
                    "dependency_count",
                    len(node.depends_on_node_ids),
                )
                try:
                    result = self._runtime.execute(
                        scientific_context,
                        task_context,
                        node,
                        binding,
                        inputs,
                        execution_cut_id=self._prepared.cut.cut_id,
                        deadline=deadline,
                    )
                except BaseException as exc:
                    if (
                        exception_failure_id(exc) is not None
                        or self._failure_materializer is None
                    ):
                        raise
                    try:
                        failure_reference = self._failure_materializer.materialize(
                            spec=DEFAULT_FAILURE_CATALOG.require(
                                "PLATFORM",
                                "EXECUTION_NODE_FAILURE",
                                "execution_node",
                            ),
                            component_id="research.execution.node",
                            context=scientific_context,
                            exc=exc,
                            correlation_refs=(
                                f"graph-node:{node.graph_node_id}",
                                f"graph-attempt:{task_context.task_id}",
                                "graph-coordinate:"
                                f"{scientific_context.graph_coordinate.coordinate_digest}",
                            ),
                        )
                    except BaseException as materialization_exc:
                        record_diagnostic_degradation(
                            self._diagnostic_degradation,
                            scientific_context,
                            subsystem="research-execution.failure-materialization",
                            stage="execution_node",
                            exc=materialization_exc,
                            correlation_refs=(
                                f"graph-node:{node.graph_node_id}",
                                f"graph-attempt:{task_context.task_id}",
                            ),
                        )
                        raise exc
                    raise ExecutionNodeFailure(
                        failure_reference
                    ) from exc
        finally:
            observation = cost_scope.observation
            if observation is not None and self._cost_observation is not None:
                delivery = attempt_secondary_delivery(
                    lambda: self._cost_observation.observe(
                        scientific_context,
                        observation,
                    )
                )
                if delivery is not None:
                    record_diagnostic_degradation(
                        self._diagnostic_degradation,
                        scientific_context,
                        subsystem="research.execution-cost",
                        stage="publish",
                        exc=RuntimeError(
                            "execution cost observation delivery failed: "
                            f"{delivery.error_type}:{delivery.error_digest}"
                        ),
                        correlation_refs=(observation.observation_digest,),
                    )
            if lifetime_lease is not None:
                lifetime_lease.release()
        task_context.checkpoint()
        self.publish_recovered_result(
            node,
            result,
            input_references=input_references,
        )

    def publish_recovered_result(
        self,
        node: ResearchExecutionBinding,
        result: JsonValue,
        *,
        input_references: dict[str, ResearchValueReference] | None = None,
    ) -> tuple[ResearchValueReference, ...]:
        if type(node) is not ResearchExecutionBinding:
            raise TypeError("recovered output publication requires compiled graph node")
        references = (
            lookup_research_node_input_references(
                self._prepared.cut.cut_id,
                self._prepared.compilation,
                node,
                self._values,
            )
            if input_references is None
            else input_references
        )
        output_references = publish_research_node_outputs(
            self._prepared.cut.cut_id,
            node,
            self._values,
            result,
        )
        self._record_artifact_lineage(references, output_references)
        return output_references

    def _record_artifact_lineage(
        self,
        input_references: dict[str, ResearchValueReference],
        output_references: tuple[ResearchValueReference, ...],
    ) -> None:
        parents = tuple(
            reference
            for reference in input_references.values()
            if reference.subject.kind is GraphStorageKind.ARTIFACT
        )
        children = tuple(
            reference
            for reference in output_references
            if reference.subject.kind is GraphStorageKind.ARTIFACT
        )
        if not parents or not children:
            return
        if self._artifact_lineage is None:
            raise ResearchExecutionUnsupported(
                "derived ARTIFACT output reached execution without lineage authority"
            )
        for parent_reference in parents:
            if parent_reference.content_digest is None:
                raise ValueError(
                    "upstream ARTIFACT reference is missing content digest"
                )
            parent_identity = ArtifactContentIdentity(
                parent_reference.authority_ref,
                parent_reference.content_digest,
            )
            for child_reference in children:
                if child_reference.content_digest is None:
                    raise ValueError(
                        "derived ARTIFACT reference is missing content digest"
                    )
                child_identity = ArtifactContentIdentity(
                    child_reference.authority_ref,
                    child_reference.content_digest,
                )
                edge = ArtifactLineageEdge(
                    parent_identity,
                    child_identity,
                    "derived_from",
                )
                stored = self._artifact_lineage.add(edge)
                if stored != edge:
                    raise RuntimeError(
                        "artifact lineage authority changed immutable provenance edge"
                    )


class StrictResearchControl(
    ResearchExecutionControlPort,
    ResearchReuseMaterializerPort,
):
    """Synchronous fail-closed product control over the durable NoetriumUnit.

    Research execution owns orchestration intent only. Lower Machine/Run/effect/checkpoint
    authorities remain the sole truth for domain execution and external effects.
    """

    def __init__(
        self,
        execution_store: ResearchGraphExecutionStorePort,
        execution_pool: ResearchExecutionPool | None,
        runtime: ResearchNodeRuntimePort,
        values: ResearchValueRouter,
        *,
        experiment_compilation: ResearchExperimentCompilationPort | None = None,
        symbol_bindings: ResearchSymbolBindingAuthorityPort | None = None,
        artifact_lineage: ArtifactLineageRelationPort | None = None,
        checkpoints: ResearchGraphCheckpointStorePort | None = None,
        cost_observation: CostObservationSinkPort | None = None,
        diagnostic_degradation: DiagnosticDegradationPort | None = None,
        failure_materializer: FailureMaterializationPort | None = None,
        lifetime_controller: ResourceLifetimeController | None = None,
        causal_event_refs: tuple[str, ...] = (),
    ) -> None:
        if not isinstance(execution_store, ResearchGraphExecutionStorePort):
            raise TypeError("Research execution control requires graph execution store")
        if not isinstance(execution_store, ResearchGraphActiveCutStorePort):
            raise TypeError("Research execution control requires active-cut CAS store")
        if not isinstance(execution_store, ResearchGraphControlStorePort):
            raise TypeError("Research execution control requires durable graph control store")
        if not isinstance(execution_store, ResearchGraphNodeControlStorePort):
            raise TypeError("Research execution control requires durable per-node control store")
        if execution_pool is not None and type(execution_pool) is not ResearchExecutionPool:
            raise TypeError(
                "Research execution execution_pool must be ResearchExecutionPool or None"
            )
        if not isinstance(runtime, ResearchNodeRuntimePort):
            raise TypeError("Research execution control requires typed node runtime")
        if type(values) is not ResearchValueRouter:
            raise TypeError("Research execution control requires typed value router")
        if experiment_compilation is not None and not isinstance(
            experiment_compilation,
            ResearchExperimentCompilationPort,
        ):
            raise TypeError(
                "Research execution control experiment_compilation must satisfy "
                "ResearchExperimentCompilationPort"
            )
        self._store = execution_store
        self._pool = execution_pool
        self._runtime = runtime
        self._values = values
        self._experiment_compilation = experiment_compilation
        if symbol_bindings is not None and not isinstance(
            symbol_bindings,
            ResearchSymbolBindingAuthorityPort,
        ):
            raise TypeError(
                "Research execution control symbol_bindings must satisfy typed port"
            )
        self._symbol_bindings = symbol_bindings
        if artifact_lineage is not None and not isinstance(
            artifact_lineage,
            ArtifactLineageRelationPort,
        ):
            raise TypeError(
                "Research execution control artifact_lineage must satisfy "
                "ArtifactLineageRelationPort"
            )
        self._artifact_lineage = artifact_lineage
        if checkpoints is not None:
            if not isinstance(checkpoints, ResearchGraphCheckpointStorePort):
                raise TypeError(
                    "Research execution control checkpoints must satisfy "
                    "ResearchGraphCheckpointStorePort"
                )
            durability = getattr(checkpoints, "durability", None)
            if type(durability) is not str or not durability.strip():
                raise TypeError(
                    "Research execution control checkpoint store requires durability metadata"
                )
        self._checkpoints = checkpoints
        if cost_observation is not None and not isinstance(
            cost_observation, CostObservationSinkPort
        ):
            raise TypeError("Research execution control cost_observation must satisfy typed port")
        if diagnostic_degradation is not None and not isinstance(
            diagnostic_degradation, DiagnosticDegradationPort
        ):
            raise TypeError(
                "Research execution control diagnostic_degradation must satisfy typed port"
            )
        self._cost_observation = cost_observation
        self._diagnostic_degradation = diagnostic_degradation
        if failure_materializer is not None and not isinstance(
            failure_materializer, FailureMaterializationPort
        ):
            raise TypeError(
                "Research execution control failure_materializer must satisfy typed port"
            )
        self._failure_materializer = failure_materializer
        self._causal_event_refs = causal_event_refs
        if lifetime_controller is not None and not isinstance(
            lifetime_controller, ResourceLifetimeController
        ):
            raise TypeError("Research execution control lifetime_controller must be typed")
        self._lifetime_controller = lifetime_controller
        # Prepared executions are immutable closures over one exact target/cut
        # generation.  Per-key locks provide single-flight reuse without
        # serializing independent portfolio targets.
        self._prepared_cache: dict[
            tuple[str, int], PreparedResearchExecution
        ] = {}
        self._prepared_key_locks: dict[tuple[str, int], object] = {}
        self._prepared_cache_lock = RLock()

    def prepare(
        self,
        target: ResearchExecutionTarget,
        portfolio: NoetriumUnit,
        *,
        cut_generation: int | None = None,
    ) -> PreparedResearchExecution:
        if type(target) is not ResearchExecutionTarget:
            raise TypeError("Research execution prepare requires typed target")
        if type(portfolio) is not NoetriumUnit:
            raise TypeError("Research execution prepare requires NoetriumUnit portfolio")
        if cut_generation is None:
            observed = self._store.active_execution_snapshot(target.execution_id)
            cut_generation = (
                1 if observed is None else observed.active_cut.generation
            )
        if type(cut_generation) is not int or cut_generation < 1:
            raise ValueError("Research execution cut_generation must be positive")

        key = (target.target_digest, cut_generation)
        with self._prepared_cache_lock:
            cached = self._prepared_cache.get(key)
            if cached is not None:
                return cached
            key_lock = self._prepared_key_locks.get(key)
            if key_lock is None:
                key_lock = RLock()
                self._prepared_key_locks[key] = key_lock

        with key_lock:
            with self._prepared_cache_lock:
                cached = self._prepared_cache.get(key)
                if cached is not None:
                    return cached
            prepared = prepare_research_execution(
                target,
                portfolio,
                self._runtime,
                self._values,
                experiment_compilation=self._experiment_compilation,
                symbol_bindings=self._symbol_bindings,
                artifact_lineage=self._artifact_lineage,
                cut_generation=cut_generation,
            )
            with self._prepared_cache_lock:
                self._prepared_cache[key] = prepared
            return prepared

    def _require_execution_pool(self) -> ResearchExecutionPool:
        pool = self._pool
        if pool is None:
            raise ResearchExecutionUnsupported(
                "Research execution execution plane is not bound to an execution pool"
            )
        return pool

    def active_revision_digest(self, execution_id: str) -> str:
        if type(execution_id) is not str or not execution_id.strip():
            raise ValueError("Research execution execution_id must be non-empty")
        observed = self._store.active_execution_snapshot(execution_id)
        if observed is None:
            raise ResearchGraphExecutionConflict(
                "Research execution execution has no active durable cut"
            )
        return observed.execution.research_revision_digest

    def _migration_reuse_proofs(
        self,
        plan: ResearchExecutionMigrationDecision,
        source: ResearchCompilationView,
        bindings: tuple[ResearchGraphExecutionBinding, ...],
        snapshot,
    ) -> tuple[ResearchReuseProof, ...]:
        if not isinstance(self._runtime, ResearchNodeReconciliationPort):
            raise ResearchExecutionUnsupported(
                "revision migration requires lower-authority execution proof support"
            )
        proofs: list[ResearchReuseProof] = []
        bindings_by_id = {row.graph_node_id: row for row in bindings}
        for graph_node_id in plan.reuse_candidate_node_ids:
            node = source.binding(graph_node_id)
            bound = bindings_by_id[graph_node_id]
            record = snapshot.node(graph_node_id)
            if record.state is not ResearchGraphLiveNodeState.SUCCEEDED:
                raise ResearchGraphExecutionConflict(
                    "reuse candidate is not durably succeeded: "
                    f"{graph_node_id}"
                )
            terminal_attempt = self._store.attempt_state(
                plan.source_cut.cut_id,
                graph_node_id,
                record.attempt_number,
            )
            if terminal_attempt.state not in {
                ResearchGraphAttemptState.SUCCEEDED,
                ResearchGraphAttemptState.RECONCILED_SUCCEEDED,
            }:
                raise ResearchGraphExecutionConflict(
                    "reuse candidate latest attempt is not proven successful: "
                    f"{graph_node_id}={terminal_attempt.state.value}"
                )
            if terminal_attempt.finished_at_ns is None:
                raise ResearchGraphExecutionConflict(
                    "reuse candidate successful attempt lacks terminal timestamp: "
                    f"{graph_node_id}"
                )
            lower_proof = self._runtime.reconcile_node(
                node,
                bound,
                execution_cut_id=plan.source_cut.cut_id,
                attempt_id=terminal_attempt.attempt_id,
            )
            if type(lower_proof) is not ResearchNodeReconciliationProof:
                raise TypeError(
                    "revision migration runtime returned invalid lower execution proof"
                )
            lower_proof.validate(
                node,
                bound,
                execution_cut_id=plan.source_cut.cut_id,
                attempt_id=terminal_attempt.attempt_id,
            )
            if (
                lower_proof.disposition
                is not ResearchGraphReconciliationDisposition.SUCCEEDED
            ):
                raise ResearchGraphExecutionConflict(
                    "reuse candidate is not proven succeeded by lower authority: "
                    f"{graph_node_id}"
                )

            output_proofs = []
            outputs = node.graph.boundary.outputs
            for output in outputs:
                subject = ResearchValueSubject(
                    plan.source_cut.cut_id,
                    graph_node_id,
                    output.name,
                    output.type_ref.storage_kind,
                    node.semantic_digest,
                )
                reference = self._values.lookup(subject)
                resolved = self._values.resolve(reference)
                if len(outputs) == 1:
                    expected = lower_proof.result
                else:
                    if not isinstance(lower_proof.result, dict):
                        raise ResearchGraphExecutionConflict(
                            "multi-output reuse proof lost canonical result mapping: "
                            f"{graph_node_id}"
                        )
                    if output.name not in lower_proof.result:
                        raise ResearchGraphExecutionConflict(
                            "multi-output reuse proof is missing declared output: "
                            f"{graph_node_id}:{output.name}"
                        )
                    expected = lower_proof.result[output.name]
                if resolved != expected:
                    raise ResearchGraphExecutionConflict(
                        "stored Research execution output does not match lower succeeded result: "
                        f"{graph_node_id}:{output.name}"
                    )
                output_proofs.append(
                    {
                        "name": output.name,
                        "kind": output.type_ref.storage_kind.value,
                        "source_reference_digest": reference.reference_digest,
                        "source_authority_reuse_proof": self._values.reuse_proof(
                            reference
                        ),
                        "resolved_value_digest": canonical_digest(resolved),
                    }
                )

            proofs.append(
                ResearchReuseProof(
                    graph_node_id,
                    plan.source_cut.cut_id,
                    node.semantic_digest,
                    canonical_digest(
                        {
                            "schema": "noetrium.research-reuse-proof.v2",
                            "lower_proof_digest": lower_proof.proof_digest,
                            "lower_authority_id": lower_proof.authority_id,
                            "lower_evidence_digests": lower_proof.evidence_digests,
                            "outputs": tuple(output_proofs),
                        }
                    ),
                )
            )
        return tuple(proofs)

    def materialize_reuse(
        self,
        plan: ResearchExecutionMigrationDecision,
        node: ResearchExecutionBinding,
        proof: ResearchReuseProof,
    ) -> str:
        if not isinstance(plan, ResearchExecutionMigrationDecision):
            raise TypeError("Research execution reuse materialization requires migration plan")
        if type(node) is not ResearchExecutionBinding:
            raise TypeError("Research execution reuse materialization requires compiled node")
        if type(proof) is not ResearchReuseProof:
            raise TypeError("Research execution reuse materialization requires reuse proof")
        if (
            proof.graph_node_id != node.graph_node_id
            or proof.source_cut_id != plan.source_cut.cut_id
            or proof.semantic_digest != node.semantic_digest
        ):
            raise ValueError("Research execution reuse materialization identity drifted")

        rows = []
        for output in node.graph.boundary.outputs:
            source_subject = ResearchValueSubject(
                plan.source_cut.cut_id,
                node.graph_node_id,
                output.name,
                output.type_ref.storage_kind,
                node.semantic_digest,
            )
            source_reference = self._values.lookup(source_subject)
            source_value = self._values.resolve(source_reference)
            source_authority_proof = self._values.reuse_proof(source_reference)
            target_subject = ResearchValueSubject(
                plan.target_cut.cut_id,
                node.graph_node_id,
                output.name,
                output.type_ref.storage_kind,
                node.semantic_digest,
            )
            target_reference = self._values.reuse(
                source_reference,
                target_subject,
            )
            target_value = self._values.resolve(target_reference)
            if target_value != source_value:
                raise ResearchGraphExecutionConflict(
                    "cross-cut value reuse changed canonical output value: "
                    f"{node.graph_node_id}:{output.name}"
                )
            if output.type_ref.storage_kind is GraphStorageKind.ARTIFACT:
                if self._artifact_lineage is None:
                    raise ResearchExecutionUnsupported(
                        "cross-cut ARTIFACT reuse requires ArtifactLineageRelationPort"
                    )
                if (
                    source_reference.content_digest is None
                    or target_reference.content_digest is None
                ):
                    raise ValueError(
                        "cross-cut ARTIFACT reuse lost immutable content digest"
                    )
                reuse_edge = ArtifactLineageEdge(
                    ArtifactContentIdentity(
                        source_reference.authority_ref,
                        source_reference.content_digest,
                    ),
                    ArtifactContentIdentity(
                        target_reference.authority_ref,
                        target_reference.content_digest,
                    ),
                    "reused_from",
                )
                stored_edge = self._artifact_lineage.add(reuse_edge)
                if stored_edge != reuse_edge:
                    raise RuntimeError(
                        "artifact lineage authority changed immutable reuse edge"
                    )
            rows.append(
                {
                    "name": output.name,
                    "kind": output.type_ref.storage_kind.value,
                    "source_reference_digest": source_reference.reference_digest,
                    "source_authority_reuse_proof": source_authority_proof,
                    "target_reference_digest": target_reference.reference_digest,
                    "target_authority_reuse_proof": self._values.reuse_proof(
                        target_reference
                    ),
                    "resolved_value_digest": canonical_digest(target_value),
                }
            )
        return canonical_digest(
            {
                "schema": "noetrium.research-reuse-materialization.v1",
                "migration_digest": plan.migration_digest,
                "source_reuse_proof": proof.proof_digest,
                "graph_node_id": node.graph_node_id,
                "outputs": tuple(rows),
            }
        )

    def migrate(
        self,
        request: ResearchControlRequest,
        source_revision: ResearchGraphRevision,
        source_portfolio: NoetriumUnit,
        target_portfolio: NoetriumUnit,
    ) -> ResearchControlReceipt:
        if type(request) is not ResearchControlRequest:
            raise TypeError("Research execution migration request must be typed")
        if request.action is not ResearchControlAction.MIGRATE:
            raise ValueError("Research execution migration requires MIGRATE action")
        self._require_whole_graph_control(request)
        if type(source_revision) is not ResearchGraphRevision:
            raise TypeError("Research execution migration source revision must be typed")
        if type(source_portfolio) is not NoetriumUnit:
            raise TypeError("Research execution migration source portfolio must be typed")
        if type(target_portfolio) is not NoetriumUnit:
            raise TypeError("Research execution migration target portfolio must be typed")
        if source_revision.portfolio_id != request.target.portfolio_id:
            raise ValueError("Research execution migration source portfolio identity drifted")
        if source_revision.revision_digest == request.target.revision.revision_digest:
            raise ResearchGraphExecutionConflict(
                "Research execution migration requires a different target revision"
            )

        source = compile_research_portfolio_graph(
            source_revision,
            source_portfolio,
        )
        target = compile_research_portfolio_graph(
            request.target.revision,
            target_portfolio,
        )
        observed = self._store.active_execution_snapshot(
            request.target.execution_id
        )
        if observed is None:
            raise ResearchGraphExecutionConflict(
                "Research execution migration source is not the active durable cut"
            )
        source_cut = ResearchExecutionCut.from_compilation(
            request.target.execution_id,
            source,
            generation=observed.active_cut.generation,
        )
        if observed.active_cut.cut_id != source_cut.cut_id:
            raise ResearchGraphExecutionConflict(
                "Research execution migration source is not the active durable cut"
            )
        active = observed.active_cut
        snapshot = observed.execution
        source_control = observed.control
        if source_control.phase is not ResearchGraphControlPhase.PAUSED:
            raise ResearchGraphExecutionConflict(
                "Research execution migration requires a paused source cut; "
                "DRAIN or PAUSE before changing revisions, "
                f"actual={source_control.phase.value}"
            )
        if snapshot.reconciliation_required_node_ids:
            raise ResearchGraphExecutionConflict(
                "Research execution migration is blocked by reconciliation debt"
            )

        plan = plan_research_execution_migration(
            request.target.execution_id,
            source,
            target,
            snapshot,
            source_generation=active.generation,
            target_generation=active.generation + 1,
        )
        if not plan.can_switch:
            raise ResearchGraphExecutionConflict(
                "Research execution migration source cut is not safely switchable"
            )

        # Prove the complete target execution closure before staging any target
        # cut state or switching the active revision.  A revision that compiles
        # but cannot be admitted by its exact lower runtime/value authorities is
        # not a safe migration target.
        target_prepared = prepare_research_execution(
            request.target,
            target_portfolio,
            self._runtime,
            self._values,
            experiment_compilation=self._experiment_compilation,
            symbol_bindings=self._symbol_bindings,
            artifact_lineage=self._artifact_lineage,
            cut_generation=active.generation + 1,
        )
        if (
            not _same_compilation_identity(target_prepared.compilation, target)
            or target_prepared.cut != plan.target_cut
        ):
            raise ValueError(
                "Research execution migration target preflight identity drifted"
            )

        source_bindings = compile_research_execution_bindings(
            source,
            experiment_compilation=self._experiment_compilation,
            symbol_bindings=self._symbol_bindings,
        )
        reuse_proofs = self._migration_reuse_proofs(
            plan,
            source,
            source_bindings,
            snapshot,
        )
        materialized = materialize_research_execution_migration(
            plan,
            target,
            self._store,
            reuse_proofs=reuse_proofs,
            reuse_materializer=self,
            now_ns=time.time_ns(),
        )
        target_control = self._store.control_state(plan.target_cut.cut_id)
        if target_control.phase is not ResearchGraphControlPhase.PAUSED:
            raise ResearchGraphExecutionConflict(
                "Research execution migration target did not remain paused after cut switch"
            )
        return self._durable_control_receipt(
            request,
            target,
            plan.target_cut,
            materialized.active_cut,
            materialized.snapshot,
            target_control,
            state="paused",
            extra={
                "migration_digest": plan.migration_digest,
                "source_cut_id": plan.source_cut.cut_id,
                "target_cut_id": plan.target_cut.cut_id,
                "reused_node_ids": materialized.reused_node_ids,
                "restart_node_ids": materialized.restart_node_ids,
                "preserved_paused_node_ids": (
                    materialized.preserved_paused_node_ids
                ),
                "preserved_cancelled_node_ids": (
                    materialized.preserved_cancelled_node_ids
                ),
                "control_transfer_digest": materialized.control_transfer_digest,
                "target_preflight_digest": target_prepared.preflight_digest,
            },
        )

    def control(
        self,
        request: ResearchControlRequest,
        portfolio: NoetriumUnit,
    ) -> ResearchControlReceipt:
        if type(request) is not ResearchControlRequest:
            raise TypeError("Research execution control request must be typed")
        if type(portfolio) is not NoetriumUnit:
            raise TypeError("Research execution control portfolio must be typed")
        if request.action is ResearchControlAction.RUN:
            return self._run(request, portfolio)
        if request.action is ResearchControlAction.INSPECT:
            return self._inspect(request, portfolio)
        if request.action is ResearchControlAction.DRAIN:
            return self._drain(request, portfolio)
        if request.action is ResearchControlAction.PAUSE:
            return self._pause(request, portfolio)
        if request.action is ResearchControlAction.INTERRUPT:
            return self._interrupt(request, portfolio)
        if request.action is ResearchControlAction.RESUME:
            return self._resume(request, portfolio)
        if request.action is ResearchControlAction.CANCEL:
            return self._cancel(request, portfolio)
        if request.action is ResearchControlAction.CHECKPOINT:
            return self._checkpoint(request, portfolio)
        if request.action is ResearchControlAction.RETRY:
            return self._retry(request, portfolio)
        if request.action is ResearchControlAction.RECONCILE:
            return self._reconcile(request, portfolio)
        raise ResearchExecutionUnsupported(
            "Research execution control action has no canonical durable implementation: "
            f"{request.action.value}"
        )

    @staticmethod
    def _require_whole_graph_control(request: ResearchControlRequest) -> None:
        if request.target.graph is not None:
            raise ResearchExecutionUnsupported(
                f"node-scoped {request.action.value.upper()} requires an exact "
                "lower-runtime control proof and is not inferred from graph state"
            )
        if request.payload is not None:
            raise ResearchExecutionUnsupported(
                f"{request.action.value.upper()} does not accept opaque control payload"
            )

    def _active_execution_state(
        self,
        request: ResearchControlRequest,
        portfolio: NoetriumUnit,
    ):
        compilation = compile_research_portfolio_graph(
            request.target.revision,
            portfolio,
        )
        observed = self._store.active_execution_snapshot(
            request.target.execution_id
        )
        if observed is None:
            raise ResearchGraphExecutionConflict(
                "Research execution execution has no active durable cut"
            )
        cut = ResearchExecutionCut.from_compilation(
            request.target.execution_id,
            compilation,
            generation=observed.active_cut.generation,
        )
        if observed.active_cut.cut_id != cut.cut_id:
            raise ResearchGraphExecutionConflict(
                "Research execution target revision is not the active durable cut"
            )
        return (
            compilation,
            cut,
            observed.active_cut,
            observed.execution,
            observed.control,
        )

    @staticmethod
    def _target_graph_node(
        request: ResearchControlRequest,
        compilation: ResearchCompilationView,
    ) -> ResearchExecutionBinding:
        if request.target.graph is None:
            raise ResearchGraphExecutionConflict("control target requires UnitRef")
        try:
            return compilation.binding_by_ref(request.target.graph)
        except KeyError as exc:
            raise ResearchGraphExecutionConflict(
                "control target does not identify exactly one graph node"
            ) from exc

    @staticmethod
    def _states(snapshot) -> JsonObject:
        return {
            state.value: tuple(
                node.node_id
                for node in snapshot.nodes
                if node.state is state
            )
            for state in ResearchGraphLiveNodeState
        }

    def _durable_control_receipt(
        self,
        request: ResearchControlRequest,
        compilation: ResearchCompilationView,
        cut: ResearchExecutionCut,
        active,
        snapshot,
        control,
        *,
        state: str | None = None,
        extra: JsonObject | None = None,
    ) -> ResearchControlReceipt:
        states = self._states(snapshot)
        resolved_state = state
        if resolved_state is None:
            if snapshot.reconciliation_required_node_ids or (
                control.phase is ResearchGraphControlPhase.RECOVERY_REQUIRED
            ):
                resolved_state = "recovery_required"
            elif control.phase is ResearchGraphControlPhase.PAUSED:
                resolved_state = "paused"
            elif control.phase is ResearchGraphControlPhase.DRAINING:
                resolved_state = "draining"
            elif control.phase is ResearchGraphControlPhase.CANCELLED:
                resolved_state = "cancelled"
            else:
                resolved_state = "durable"
        node_rows = []
        for node_record in snapshot.nodes:
            node_control = self._store.node_control_state(
                cut.cut_id,
                node_record.node_id,
            )
            node_rows.append({
                "graph_node_id": node_record.node_id,
                "state": node_record.state.value,
                "attempt_number": node_record.attempt_number,
                "attempt_id": node_record.attempt_id,
                "failure_type": node_record.failure_type,
                "failure_message": node_record.failure_message,
                "failure_provenance": (
                    None
                    if node_record.failure_provenance is None
                    else node_record.failure_provenance.as_payload()
                ),
                "blocked_by_node_ids": node_record.blocked_by_node_ids,
                "control_phase": node_control.phase.value,
                "control_generation": node_control.generation,
            })
        payload: JsonObject = {
            "cut_id": cut.cut_id,
            "graph_digest": compilation.graph_digest,
            "generation": snapshot.generation,
            "active_cut_generation": active.generation,
            "control_phase": control.phase.value,
            "control_generation": control.generation,
            "static_node_count": compilation.root_scope.node_count,
            "materialized_node_count": len(snapshot.nodes),
            "states": states,
            "nodes": tuple(node_rows),
        }
        if request.target.graph is not None:
            target_node = self._target_graph_node(request, compilation)
            try:
                node_record = snapshot.node(target_node.graph_node_id)
            except KeyError:
                payload["node"] = {
                    "graph_node_id": target_node.graph_node_id,
                    "state": "unmaterialized",
                    "attempt_number": 0,
                    "attempt_id": None,
                    "failure_type": None,
                    "failure_message": None,
                    "failure_provenance": None,
                    "blocked_by_node_ids": (),
                    "control_phase": None,
                    "control_generation": None,
                }
            else:
                node_control = self._store.node_control_state(
                    cut.cut_id,
                    target_node.graph_node_id,
                )
                payload["node"] = {
                    "graph_node_id": target_node.graph_node_id,
                    "state": node_record.state.value,
                    "attempt_number": node_record.attempt_number,
                    "attempt_id": node_record.attempt_id,
                    "failure_type": node_record.failure_type,
                    "failure_message": node_record.failure_message,
                    "failure_provenance": (
                        None
                        if node_record.failure_provenance is None
                        else node_record.failure_provenance.as_payload()
                    ),
                    "blocked_by_node_ids": node_record.blocked_by_node_ids,
                    "control_phase": node_control.phase.value,
                    "control_generation": node_control.generation,
                }
        if extra:
            payload.update(extra)
        return ResearchControlReceipt(
            request.action,
            request.target,
            resolved_state,
            canonical_digest(
                {
                    "action": request.action.value,
                    "target_digest": request.target.target_digest,
                    "state": resolved_state,
                    "payload": payload,
                }
            ),
            payload,
        )

    def _activate_run_cut(
        self,
        execution_id: str,
        compilation: ResearchCompilationView,
        cut: ResearchExecutionCut,
    ) -> ResearchExecutionActivation:
        """Activate one RUN cut without overriding explicit user control intent.

        A clean terminal cut may roll to a fresh physical generation. A different
        scientific revision may hot-replace only when the managed runtime can prove
        exclusive owner-generation authority and the source is either explicitly
        paused or provably abandoned. Otherwise revision changes require MIGRATE.
        """
        expected = ResearchExecutionCut.from_compilation(
            execution_id,
            compilation,
            generation=cut.generation,
        )
        if cut != expected:
            raise ValueError("Research execution RUN cut identity drifted from compilation")
        observed = self._store.active_execution_snapshot(execution_id)
        if observed is None or observed.active_cut.cut_id == cut.cut_id:
            return activate_research_execution_cut(
                execution_id,
                compilation,
                self._store,
                generation=cut.generation,
            )

        source_cut_id = observed.active_cut.cut_id
        snapshot = observed.execution
        same_scientific_cut = (
            observed.active_cut.research_revision_digest
            == cut.research_revision_digest
            and observed.active_cut.graph_digest == cut.graph_digest
        )
        now_ns = time.time_ns()

        if same_scientific_cut:
            clean_terminal_states = {
                ResearchGraphLiveNodeState.SUCCEEDED,
                ResearchGraphLiveNodeState.REUSED,
            }
            source_control = self._store.control_state(source_cut_id)
            if (
                len(snapshot.nodes) != compilation.root_scope.node_count
                or any(
                    node.state not in clean_terminal_states
                    for node in snapshot.nodes
                )
                or snapshot.reconciliation_required_node_ids
                or source_control.phase in {
                    ResearchGraphControlPhase.CANCELLED,
                    ResearchGraphControlPhase.RECOVERY_REQUIRED,
                }
            ):
                raise ResearchGraphExecutionConflict(
                    "fresh Research execution generation requires a clean terminal source cut"
                )
        else:
            if (
                not self._require_execution_pool().can_recover_abandoned_owner_generations
                or not isinstance(
                    self._store, ResearchGraphOwnerGenerationRecoveryPort
                )
            ):
                raise ResearchGraphExecutionConflict(
                    "logical Research execution execution is already bound to a different "
                    "active cut; revision changes require explicit migration"
                )
            snapshot = self._store.recover_abandoned_owner_generation(
                source_cut_id,
                current_owner_generation_id=self._require_execution_pool().owner_generation_id,
                now_ns=now_ns,
            )
            snapshot = self._store.recover_expired(source_cut_id, now_ns=now_ns)

        still_active = tuple(
            node.node_id
            for node in snapshot.nodes
            if node.state in {
                ResearchGraphLiveNodeState.CLAIMED,
                ResearchGraphLiveNodeState.RUNNING,
            }
        )
        if still_active:
            raise ResearchGraphExecutionConflict(
                "logical Research execution execution still has live work in the active cut; "
                f"revision supersession refused: {still_active}"
            )

        source_control = self._store.control_state(source_cut_id)
        if snapshot.reconciliation_required_node_ids:
            if same_scientific_cut:
                raise ResearchGraphExecutionConflict(
                    "fresh Research execution generation cannot supersede reconciliation debt"
                )
            if source_control.phase in {
                ResearchGraphControlPhase.ACTIVE,
                ResearchGraphControlPhase.DRAINING,
            }:
                source_control = self._store.require_recovery(
                    source_cut_id,
                    expected_generation=source_control.generation,
                    now_ns=now_ns,
                )
            elif source_control.phase is not ResearchGraphControlPhase.RECOVERY_REQUIRED:
                raise ResearchGraphExecutionConflict(
                    "abandoned source cut has reconciliation debt in an incompatible "
                    f"control phase: {source_control.phase.value}"
                )
        elif (
            not same_scientific_cut
            and source_control.phase is not ResearchGraphControlPhase.PAUSED
        ):
            raise ResearchGraphExecutionConflict(
                "revision hot replacement requires an explicitly paused source cut; "
                "otherwise use explicit migration"
            )

        target_snapshot = self._store.ensure_execution_identity(
            cut.cut_id,
            compilation.execution_unit,
        )
        active = self._store.active_cut(execution_id)
        if active is None or active.cut_id != source_cut_id:
            raise ResearchGraphExecutionConflict(
                "research active cut changed while RUN cut switch was fenced"
            )
        source_snapshot = self._store.snapshot(source_cut_id)
        source_control = self._store.control_state(source_cut_id)
        source_fence = ResearchGraphCutSwitchFence(
            source_cut_id,
            active.generation,
            source_snapshot.generation,
            source_control,
            tuple(
                self._store.node_control_state(source_cut_id, node.node_id)
                for node in source_snapshot.nodes
            ),
        )
        active = self._store.move_active_cut(
            execution_id,
            cut.cut_id,
            expected_cut_id=source_cut_id,
            source_fence=source_fence,
        )
        return ResearchExecutionActivation(cut, active, target_snapshot)

    def _recover_abandoned_run_nodes(
        self,
        request: ResearchControlRequest,
        portfolio: NoetriumUnit,
        prepared: PreparedResearchExecution,
        activation: ResearchExecutionActivation,
    ) -> tuple[str, ...]:
        """Reconcile only work fenced as abandoned by this RUN generation.

        User-driven interrupt/recovery intent is deliberately excluded: only a
        node observed RUNNING before this call and changed to RECONCILE_REQUIRED
        by the exclusive owner-generation fence is eligible for automatic
        recovery.  Lower authority remains the sole source of the disposition.
        """
        if (
            not self._require_execution_pool().can_recover_abandoned_owner_generations
            or not isinstance(self._store, ResearchGraphOwnerGenerationRecoveryPort)
        ):
            return ()
        before = activation.snapshot
        after = self._store.recover_abandoned_owner_generation(
            activation.cut.cut_id,
            current_owner_generation_id=self._require_execution_pool().owner_generation_id,
            now_ns=time.time_ns(),
        )
        abandoned = tuple(
            node.node_id
            for node in before.nodes
            if node.state is ResearchGraphLiveNodeState.RUNNING
            and after.node(node.node_id).state
            is ResearchGraphLiveNodeState.RECONCILE_REQUIRED
        )
        for graph_node_id in abandoned:
            compiled = prepared.compilation.binding(graph_node_id)
            recovery_target = request.target.for_graph(compiled.ref.path)
            self._reconcile(
                ResearchControlRequest(
                    ResearchControlAction.RECONCILE,
                    recovery_target,
                ),
                portfolio,
            )
            node_control = self._store.node_control_state(
                activation.cut.cut_id,
                graph_node_id,
            )
            if node_control.phase is ResearchGraphNodeControlPhase.PAUSED:
                resumed = self._store.resume_node(
                    activation.cut.cut_id,
                    graph_node_id,
                    expected_generation=node_control.generation,
                    now_ns=time.time_ns(),
                )
                if resumed.phase is not ResearchGraphNodeControlPhase.ACTIVE:
                    raise ResearchGraphExecutionConflict(
                        "automatic abandoned-generation recovery did not reactivate "
                        f"node control: {graph_node_id}={resumed.phase.value}"
                    )
        return abandoned

    def _run(
        self,
        request: ResearchControlRequest,
        portfolio: NoetriumUnit,
    ) -> ResearchControlReceipt:
        if request.payload is not None:
            raise ResearchExecutionUnsupported(
                "RUN payload requires declared root-input semantics; implicit global "
                "payload injection is forbidden"
            )
        observed = self._store.active_execution_snapshot(
            request.target.execution_id
        )
        provisional_generation = (
            1 if observed is None else observed.active_cut.generation
        )
        prepared = self.prepare(
            request.target,
            portfolio,
            cut_generation=provisional_generation,
        )
        if observed is not None:
            same_scientific_cut = (
                observed.active_cut.research_revision_digest
                == prepared.cut.research_revision_digest
                and observed.active_cut.graph_digest == prepared.cut.graph_digest
            )
            clean_terminal_states = {
                ResearchGraphLiveNodeState.SUCCEEDED,
                ResearchGraphLiveNodeState.REUSED,
            }
            clean_terminal_rerun = (
                same_scientific_cut
                and len(observed.execution.nodes)
                == prepared.compilation.root_scope.node_count
                and all(
                    node.state in clean_terminal_states
                    for node in observed.execution.nodes
                )
                and not observed.execution.reconciliation_required_node_ids
                and observed.control.phase
                not in {
                    ResearchGraphControlPhase.CANCELLED,
                    ResearchGraphControlPhase.RECOVERY_REQUIRED,
                }
            )
            exclusive_revision_replacement = (
                not same_scientific_cut
                and self._require_execution_pool().can_recover_abandoned_owner_generations
                and isinstance(
                    self._store, ResearchGraphOwnerGenerationRecoveryPort
                )
            )
            if clean_terminal_rerun or exclusive_revision_replacement:
                prepared = replace(
                    prepared,
                    cut=ResearchExecutionCut.from_compilation(
                        request.target.execution_id,
                        prepared.compilation,
                        generation=observed.active_cut.generation + 1,
                    ),
                )
        activation = self._activate_run_cut(
            request.target.execution_id,
            prepared.compilation,
            prepared.cut,
        )
        if activation.cut != prepared.cut:
            raise ValueError("Research execution active cut drifted from preflight cut")
        self._recover_abandoned_run_nodes(
            request,
            portfolio,
            prepared,
            activation,
        )
        control = self._store.control_state(prepared.cut.cut_id)
        snapshot = self._store.snapshot(prepared.cut.cut_id)

        # Explicit user recovery/cancellation intent is sticky. RUN may repair only
        # owner-generation abandonment proven inside _recover_abandoned_run_nodes.
        if control.phase is ResearchGraphControlPhase.RECOVERY_REQUIRED:
            return self._durable_control_receipt(
                request,
                prepared.compilation,
                prepared.cut,
                activation.active_cut,
                snapshot,
                control,
            )
        if control.phase is ResearchGraphControlPhase.CANCELLED:
            return self._durable_control_receipt(
                request,
                prepared.compilation,
                prepared.cut,
                activation.active_cut,
                snapshot,
                control,
            )

        if control.phase is ResearchGraphControlPhase.DRAINING:
            live = tuple(
                node.node_id
                for node in snapshot.nodes
                if node.state in {
                    ResearchGraphLiveNodeState.CLAIMED,
                    ResearchGraphLiveNodeState.RUNNING,
                    ResearchGraphLiveNodeState.RECONCILE_REQUIRED,
                }
            )
            if live:
                raise ResearchGraphExecutionConflict(
                    "RUN cannot supersede a still-draining live cut: "
                    f"{live}"
                )
            control = self._store.pause_if_quiescent(
                prepared.cut.cut_id,
                expected_generation=control.generation,
                now_ns=time.time_ns(),
            )
        if control.phase is ResearchGraphControlPhase.PAUSED:
            control = self._store.resume(
                prepared.cut.cut_id,
                expected_generation=control.generation,
                now_ns=time.time_ns(),
            )
        if control.phase is not ResearchGraphControlPhase.ACTIVE:
            raise ResearchGraphExecutionConflict(
                "RUN requires an active or resumable graph control phase; "
                f"actual={control.phase.value}"
            )

        if prepared.selected_node_ids:
            self._store.materialize_nodes(
                prepared.cut.cut_id,
                prepared.compilation.execution_unit,
                prepared.selected_node_ids,
            )
        snapshot = self._store.snapshot(prepared.cut.cut_id)
        non_resumable_states = {
            ResearchGraphLiveNodeState.SUCCEEDED,
            ResearchGraphLiveNodeState.REUSED,
            ResearchGraphLiveNodeState.FAILED,
            ResearchGraphLiveNodeState.CANCELLED,
            ResearchGraphLiveNodeState.RECONCILE_REQUIRED,
        }
        for graph_node_id in prepared.selected_node_ids:
            record = snapshot.node(graph_node_id)
            node_control = self._store.node_control_state(
                prepared.cut.cut_id, graph_node_id
            )
            if node_control.phase is ResearchGraphNodeControlPhase.RECOVERY_REQUIRED:
                return self._durable_control_receipt(
                    request,
                    prepared.compilation,
                    prepared.cut,
                    activation.active_cut,
                    snapshot,
                    control,
                    state="node_recovery_required",
                    extra={
                        "node_control_halt": ({
                            "node_id": graph_node_id,
                            "phase": node_control.phase.value,
                            "generation": node_control.generation,
                        },),
                    },
                )
            if node_control.phase is ResearchGraphNodeControlPhase.DRAINING:
                if record.state in {
                    ResearchGraphLiveNodeState.CLAIMED,
                    ResearchGraphLiveNodeState.RUNNING,
                }:
                    raise ResearchGraphExecutionConflict(
                        "RUN cannot resume a node that is still draining live work: "
                        f"{graph_node_id}"
                    )
                node_control = self._store.pause_node_if_quiescent(
                    prepared.cut.cut_id,
                    graph_node_id,
                    expected_generation=node_control.generation,
                    now_ns=time.time_ns(),
                )
            if (
                node_control.phase is ResearchGraphNodeControlPhase.PAUSED
                and record.state not in non_resumable_states
            ):
                self._store.resume_node(
                    prepared.cut.cut_id,
                    graph_node_id,
                    expected_generation=node_control.generation,
                    now_ns=time.time_ns(),
                )
        return self._drive(
            request,
            prepared,
            activation.active_cut.generation,
        )

    def _drive(
        self,
        request: ResearchControlRequest,
        prepared: PreparedResearchExecution,
        active_cut_generation: int,
    ) -> ResearchControlReceipt:
        executor = PreparedResearchNodeExecutor(
            prepared,
            self._runtime,
            self._values,
            artifact_lineage=self._artifact_lineage,
            cost_observation=self._cost_observation,
            diagnostic_degradation=self._diagnostic_degradation,
            failure_materializer=self._failure_materializer,
            lifetime_controller=self._lifetime_controller,
            causal_event_refs=self._causal_event_refs,
        )
        scheduler = bind_research_portfolio_scheduler(
            prepared.compilation,
            executor,
            execution_pool=self._require_execution_pool(),
            tenant_id=prepared.target.portfolio_id,
            execution_store=self._store,
            execution_id=prepared.cut.cut_id,
            task_group_id=(
                "research:"
                f"{prepared.target.execution_id}:{prepared.cut.cut_id}"
            ),
            selected_node_ids=prepared.selected_node_ids,
        )
        fleet_group = self._require_execution_pool().open_fleet_group(
            (
                "research-fleet:"
                f"{prepared.target.portfolio_id}:"
                f"{prepared.target.execution_id}:{prepared.cut.cut_id}"
            ),
            tenant_id=prepared.target.portfolio_id,
            resource_id=f"research-fleet:{prepared.target.execution_id}",
        )

        def run_portfolio(task_context: TaskContextPort):
            task_context.checkpoint()
            value = scheduler.execute()
            task_context.checkpoint()
            return value

        try:
            try:
                fleet_handle = fleet_group.submit(
                    ExecutionSpec(
                        task_id=(
                            "research-fleet-run:"
                            f"{prepared.target.execution_id}:{prepared.cut.cut_id}"
                        ),
                        lane_kind=ExecutionLaneKind.BLOCKING_IO,
                        failure_scope=TaskFailureScope.CALLER,
                    ),
                    run_portfolio,
                )
                report = fleet_handle.result()
            except ResearchGraphControlHalt:
                observed = self._store.active_execution_snapshot(
                    request.target.execution_id
                )
                if (
                    observed is None
                    or observed.active_cut.cut_id != prepared.cut.cut_id
                ):
                    raise ResearchGraphExecutionConflict(
                        "Research execution active cut changed while control halt was observed"
                    )
                return self._durable_control_receipt(
                    request,
                    prepared.compilation,
                    prepared.cut,
                    observed.active_cut,
                    observed.execution,
                    observed.control,
                )
            except ResearchGraphNodeControlHalt as halt:
                observed = self._store.active_execution_snapshot(
                    request.target.execution_id
                )
                if (
                    observed is None
                    or observed.active_cut.cut_id != prepared.cut.cut_id
                ):
                    raise ResearchGraphExecutionConflict(
                        "Research execution active cut changed while node control halt was observed"
                    )
                recovery = any(
                    row.phase is ResearchGraphNodeControlPhase.RECOVERY_REQUIRED
                    for row in halt.controls
                )
                return self._durable_control_receipt(
                    request,
                    prepared.compilation,
                    prepared.cut,
                    observed.active_cut,
                    observed.execution,
                    observed.control,
                    state=(
                        "node_recovery_required"
                        if recovery
                        else "node_paused"
                    ),
                    extra={
                        "node_control_halt": tuple(
                            {
                                "node_id": row.node_id,
                                "phase": row.phase.value,
                                "generation": row.generation,
                            }
                            for row in halt.controls
                        )
                    },
                )
        finally:
            close_errors: list[BaseException] = []
            try:
                scheduler.close()
            except BaseException as exc:
                close_errors.append(exc)
            try:
                self._require_execution_pool().close_fleet_group(
                    fleet_group,
                    cancel_pending=False,
                )
            except BaseException as exc:
                close_errors.append(exc)
            if close_errors:
                raise ExceptionGroup(
                    "Research execution fleet execution shutdown failed",
                    close_errors,
                )
        return self._execution_receipt(
            request,
            prepared,
            active_cut_generation,
            report,
        )

    def _inspect(
        self,
        request: ResearchControlRequest,
        portfolio: NoetriumUnit,
    ) -> ResearchControlReceipt:
        compilation, cut, active, snapshot, control = self._active_execution_state(
            request,
            portfolio,
        )
        return self._durable_control_receipt(
            request,
            compilation,
            cut,
            active,
            snapshot,
            control,
        )

    def _drain(
        self,
        request: ResearchControlRequest,
        portfolio: NoetriumUnit,
    ) -> ResearchControlReceipt:
        if request.payload is not None:
            raise ResearchExecutionUnsupported("DRAIN does not accept opaque control payload")
        compilation, cut, active, snapshot, control = self._active_execution_state(
            request, portfolio,
        )
        if request.target.graph is not None:
            node = self._target_graph_node(request, compilation)
            self._store.materialize_nodes(
                cut.cut_id,
                compilation.execution_unit,
                (node.graph_node_id,),
            )
            node_control = self._store.node_control_state(cut.cut_id, node.graph_node_id)
            node_control = self._store.request_node_drain(
                cut.cut_id,
                node.graph_node_id,
                expected_generation=node_control.generation,
                now_ns=time.time_ns(),
            )
            record = self._store.node_state(cut.cut_id, node.graph_node_id)
            if record.state not in {
                ResearchGraphLiveNodeState.CLAIMED,
                ResearchGraphLiveNodeState.RUNNING,
                ResearchGraphLiveNodeState.RECONCILE_REQUIRED,
            }:
                node_control = self._store.pause_node_if_quiescent(
                    cut.cut_id,
                    node.graph_node_id,
                    expected_generation=node_control.generation,
                    now_ns=time.time_ns(),
                )
            snapshot = self._store.snapshot(cut.cut_id)
            return self._durable_control_receipt(
                request, compilation, cut, active, snapshot, control,
                state=(
                    "node_paused"
                    if node_control.phase is ResearchGraphNodeControlPhase.PAUSED
                    else "node_draining"
                ),
            )
        transition_now_ns = time.time_ns()
        control = self._store.request_drain(
            cut.cut_id,
            expected_generation=control.generation,
            now_ns=transition_now_ns,
        )
        snapshot = self._store.snapshot(cut.cut_id)
        active_nodes = tuple(
            node.node_id
            for node in snapshot.nodes
            if node.state in {
                ResearchGraphLiveNodeState.CLAIMED,
                ResearchGraphLiveNodeState.RUNNING,
            }
        )
        if not active_nodes and not snapshot.reconciliation_required_node_ids:
            control = self._store.pause_if_quiescent(
                cut.cut_id,
                expected_generation=control.generation,
                now_ns=transition_now_ns,
            )
            snapshot = self._store.snapshot(cut.cut_id)
        return self._durable_control_receipt(
            request, compilation, cut, active, snapshot, control,
        )

    def _pause(
        self,
        request: ResearchControlRequest,
        portfolio: NoetriumUnit,
    ) -> ResearchControlReceipt:
        if request.payload is not None:
            raise ResearchExecutionUnsupported("PAUSE does not accept opaque control payload")
        compilation, cut, active, _snapshot, control = self._active_execution_state(
            request, portfolio,
        )
        if request.target.graph is not None:
            node = self._target_graph_node(request, compilation)
            self._store.materialize_nodes(
                cut.cut_id,
                compilation.execution_unit,
                (node.graph_node_id,),
            )
            node_control = self._store.node_control_state(cut.cut_id, node.graph_node_id)
            node_control = self._store.pause_node_if_quiescent(
                cut.cut_id,
                node.graph_node_id,
                expected_generation=node_control.generation,
                now_ns=time.time_ns(),
            )
            snapshot = self._store.snapshot(cut.cut_id)
            return self._durable_control_receipt(
                request, compilation, cut, active, snapshot, control,
                state="node_paused",
            )
        control = self._store.pause_if_quiescent(
            cut.cut_id,
            expected_generation=control.generation,
            now_ns=time.time_ns(),
        )
        snapshot = self._store.snapshot(cut.cut_id)
        return self._durable_control_receipt(
            request, compilation, cut, active, snapshot, control,
            state="paused",
        )

    def _interrupt(
        self,
        request: ResearchControlRequest,
        portfolio: NoetriumUnit,
    ) -> ResearchControlReceipt:
        if request.payload is not None:
            raise ResearchExecutionUnsupported("INTERRUPT does not accept opaque control payload")
        compilation, cut, active, _snapshot, control = self._active_execution_state(
            request, portfolio,
        )
        if request.target.graph is not None:
            node = self._target_graph_node(request, compilation)
            self._store.materialize_nodes(
                cut.cut_id,
                compilation.execution_unit,
                (node.graph_node_id,),
            )
            node_control = self._store.node_control_state(cut.cut_id, node.graph_node_id)
            node_control = self._store.interrupt_node(
                cut.cut_id,
                node.graph_node_id,
                expected_generation=node_control.generation,
                now_ns=time.time_ns(),
            )
            snapshot = self._store.snapshot(cut.cut_id)
            return self._durable_control_receipt(
                request, compilation, cut, active, snapshot, control,
                state=(
                    "node_recovery_required"
                    if node_control.phase is ResearchGraphNodeControlPhase.RECOVERY_REQUIRED
                    else "node_paused"
                ),
            )
        control = self._store.interrupt(
            cut.cut_id,
            expected_generation=control.generation,
            now_ns=time.time_ns(),
        )
        snapshot = self._store.snapshot(cut.cut_id)
        return self._durable_control_receipt(
            request, compilation, cut, active, snapshot, control,
        )

    def _resume(
        self,
        request: ResearchControlRequest,
        portfolio: NoetriumUnit,
    ) -> ResearchControlReceipt:
        if request.payload is not None:
            raise ResearchExecutionUnsupported("RESUME does not accept opaque control payload")
        compilation, cut, active, _snapshot, control = self._active_execution_state(
            request, portfolio,
        )
        # RESUME is an execution-producing transition. Prove the exact target
        # closure before changing durable control from PAUSED to ACTIVE so an
        # admission failure cannot leave a falsely runnable cut behind.
        prepared = prepare_research_execution(
            request.target,
            portfolio,
            self._runtime,
            self._values,
            experiment_compilation=self._experiment_compilation,
            symbol_bindings=self._symbol_bindings,
            artifact_lineage=self._artifact_lineage,
            cut_generation=active.generation,
        )
        if not _same_compilation_identity(prepared.compilation, compilation) or prepared.cut != cut:
            raise ValueError("Research execution resume preflight identity drifted")

        if request.target.graph is not None:
            if control.phase is not ResearchGraphControlPhase.ACTIVE:
                raise ResearchGraphExecutionConflict(
                    "node resume requires active graph-wide control; "
                    f"actual={control.phase.value}"
                )
            node = self._target_graph_node(request, compilation)
            node_control = self._store.node_control_state(cut.cut_id, node.graph_node_id)
            node_control = self._store.resume_node(
                cut.cut_id,
                node.graph_node_id,
                expected_generation=node_control.generation,
                now_ns=time.time_ns(),
            )
            if node_control.phase is not ResearchGraphNodeControlPhase.ACTIVE:
                raise ResearchGraphExecutionConflict(
                    "Research execution node resume did not produce active node control"
                )
        else:
            control = self._store.resume(
                cut.cut_id,
                expected_generation=control.generation,
                now_ns=time.time_ns(),
            )
            if control.phase is not ResearchGraphControlPhase.ACTIVE:
                raise ResearchGraphExecutionConflict(
                    "Research execution resume did not produce active graph control"
                )
        return self._drive(request, prepared, active.generation)

    def _release_cancelled_cut_values(
        self,
        compilation: ResearchCompilationView,
        *,
        execution_cut_id: str,
    ) -> tuple[str, ...]:
        """Release execution-owned value pins after durable whole-cut cancellation.

        CANCELLED is the irreversible graph-control boundary.  This step only
        releases lower-authority retention reasons; it never deletes immutable
        content, catalog records or lineage.
        """

        proofs: list[str] = []
        for node in compilation.bindings:
            for output in node.graph.boundary.outputs:
                subject = ResearchValueSubject(
                    execution_cut_id,
                    node.graph_node_id,
                    output.name,
                    output.type_ref.storage_kind,
                    node.semantic_digest,
                )
                proof = self._values.release_execution(subject)
                if proof is not None:
                    proofs.append(proof)
        return tuple(proofs)

    def _cancel(
        self,
        request: ResearchControlRequest,
        portfolio: NoetriumUnit,
    ) -> ResearchControlReceipt:
        if request.payload is not None:
            raise ResearchExecutionUnsupported("CANCEL does not accept opaque control payload")
        compilation, cut, active, _snapshot, control = self._active_execution_state(
            request, portfolio,
        )
        if request.target.graph is not None:
            node = self._target_graph_node(request, compilation)
            descendants = self._retry_descendants(
                compilation,
                node.graph_node_id,
            )
            affected = (node.graph_node_id, *descendants)
            self._store.materialize_nodes(
                cut.cut_id,
                compilation.execution_unit,
                affected,
            )
            node_control = self._store.node_control_state(
                cut.cut_id,
                node.graph_node_id,
            )
            self._store.cancel_node_subgraph(
                cut.cut_id,
                node.graph_node_id,
                descendant_node_ids=descendants,
                expected_generation=node_control.generation,
                now_ns=time.time_ns(),
            )
            snapshot = self._store.snapshot(cut.cut_id)
            return self._durable_control_receipt(
                request, compilation, cut, active, snapshot, control,
                state="node_cancelled",
                extra={"cancelled_descendant_node_ids": descendants},
            )
        control = self._store.cancel_if_quiescent(
            cut.cut_id,
            expected_generation=control.generation,
            now_ns=time.time_ns(),
        )
        snapshot = self._store.snapshot(cut.cut_id)
        release_proofs = self._release_cancelled_cut_values(
            compilation,
            execution_cut_id=cut.cut_id,
        )
        return self._durable_control_receipt(
            request, compilation, cut, active, snapshot, control,
            state="cancelled",
            extra={
                "value_release_proof_digests": release_proofs,
            },
        )

    @staticmethod
    def _retry_descendants(
        compilation: ResearchCompilationView,
        root_node_id: str,
    ) -> tuple[str, ...]:
        return compilation.descendants(root_node_id)

    def _retry(
        self,
        request: ResearchControlRequest,
        portfolio: NoetriumUnit,
    ) -> ResearchControlReceipt:
        if request.payload is not None:
            raise ResearchExecutionUnsupported(
                "RETRY does not accept an opaque retry policy payload"
            )
        if request.target.graph is None:
            raise ResearchExecutionUnsupported(
                "RETRY requires an explicit UnitRef; whole-portfolio retry "
                "would hide the failed scientific boundary"
            )
        compilation, cut, active, snapshot, control = self._active_execution_state(
            request,
            portfolio,
        )
        if control.phase not in {
            ResearchGraphControlPhase.ACTIVE,
            ResearchGraphControlPhase.PAUSED,
        }:
            raise ResearchGraphExecutionConflict(
                "research graph retry requires active or paused control, "
                f"actual={control.phase.value}"
            )
        root = self._target_graph_node(request, compilation)
        root_control = self._store.node_control_state(
            cut.cut_id,
            root.graph_node_id,
        )
        if root_control.phase not in {
            ResearchGraphNodeControlPhase.ACTIVE,
            ResearchGraphNodeControlPhase.PAUSED,
        }:
            raise ResearchGraphExecutionConflict(
                "research graph retry root control must be active or paused, "
                f"actual={root_control.phase.value}"
            )
        materialized_node_ids = {node.node_id for node in snapshot.nodes}
        descendants = tuple(
            node_id
            for node_id in self._retry_descendants(
                compilation,
                root.graph_node_id,
            )
            if node_id in materialized_node_ids
        )
        retry_seed_node_ids = (root.graph_node_id, *descendants)
        staged = (
            control.phase is ResearchGraphControlPhase.PAUSED
            or root_control.phase is ResearchGraphNodeControlPhase.PAUSED
        )

        prepared = None
        if not staged:
            # Active RETRY immediately produces execution. Admission therefore
            # precedes the durable failed-subgraph reset; otherwise an admission
            # failure would erase the failed state without launching a retry.
            execution_target = ResearchExecutionTarget(
                request.target.execution_id,
                request.target.revision,
            )
            prepared = prepare_research_execution(
                execution_target,
                portfolio,
                self._runtime,
                self._values,
                experiment_compilation=self._experiment_compilation,
                symbol_bindings=self._symbol_bindings,
                artifact_lineage=self._artifact_lineage,
                selection_seed_node_ids=retry_seed_node_ids,
                cut_generation=active.generation,
            )
            if not _same_compilation_identity(prepared.compilation, compilation) or prepared.cut != cut:
                raise ValueError("Research execution retry preflight identity drifted")

        self._store.retry_failed_subgraph(
            cut.cut_id,
            root.graph_node_id,
            descendant_node_ids=descendants,
            retry_not_before_ns=time.time_ns(),
        )
        if staged:
            snapshot = self._store.snapshot(cut.cut_id)
            return self._durable_control_receipt(
                request,
                compilation,
                cut,
                active,
                snapshot,
                control,
                state="retry_staged",
                extra={
                    "retry_root_node_id": root.graph_node_id,
                    "retry_descendant_node_ids": descendants,
                    "retry_root_control_phase": root_control.phase.value,
                },
            )
        if prepared is None:
            raise AssertionError("active retry lost preflighted execution")
        return self._drive(request, prepared, active.generation)

    def _reconcile_graph_wide(
        self,
        request: ResearchControlRequest,
        portfolio: NoetriumUnit,
    ) -> ResearchControlReceipt:
        compilation, cut, active, snapshot, control = self._active_execution_state(
            request,
            portfolio,
        )
        frontier = tuple(sorted(snapshot.reconciliation_required_node_ids))
        if not frontier:
            raise ResearchGraphExecutionConflict(
                "graph-wide RECONCILE requires reconciliation debt"
            )

        prepared = prepare_research_execution(
            request.target,
            portfolio,
            self._runtime,
            self._values,
            experiment_compilation=self._experiment_compilation,
            symbol_bindings=self._symbol_bindings,
            artifact_lineage=self._artifact_lineage,
            cut_generation=active.generation,
        )
        if (
            not _same_compilation_identity(prepared.compilation, compilation)
            or prepared.cut != cut
        ):
            raise ValueError("Research execution reconciliation preflight identity drifted")

        nodes_by_id = {
            node.graph_node_id: node
            for node in compilation.bindings
        }
        missing = tuple(node_id for node_id in frontier if node_id not in nodes_by_id)
        if missing:
            raise RuntimeError(
                "reconciliation frontier contains unbound graph nodes: "
                f"{missing}"
            )
        recovered_executor = PreparedResearchNodeExecutor(
            prepared,
            self._runtime,
            self._values,
            artifact_lineage=self._artifact_lineage,
            cost_observation=self._cost_observation,
            diagnostic_degradation=self._diagnostic_degradation,
            failure_materializer=self._failure_materializer,
            lifetime_controller=self._lifetime_controller,
            causal_event_refs=self._causal_event_refs,
        )
        proof_rows = []
        for node_id in frontier:
            node = nodes_by_id[node_id]
            record = self._store.snapshot(cut.cut_id).node(node_id)
            if record.state is not ResearchGraphLiveNodeState.RECONCILE_REQUIRED:
                raise ResearchGraphExecutionConflict(
                    "reconciliation frontier node no longer requires reconciliation: "
                    f"{node_id}"
                )
            if record.attempt_id is None:
                raise RuntimeError(
                    "reconciliation-required node lost attempt identity: "
                    f"{node_id}"
                )
            binding = prepared.binding(node_id)
            proof = self._runtime.reconcile_node(
                node,
                binding,
                execution_cut_id=cut.cut_id,
                attempt_id=record.attempt_id,
            )
            if type(proof) is not ResearchNodeReconciliationProof:
                raise TypeError("Research execution runtime returned invalid reconciliation proof")
            proof.validate(
                node,
                binding,
                execution_cut_id=cut.cut_id,
                attempt_id=record.attempt_id,
            )
            if proof.disposition is ResearchGraphReconciliationDisposition.SUCCEEDED:
                recovered_executor.publish_recovered_result(node, proof.result)

            transition_now_ns = time.time_ns()
            self._store.resolve_reconciliation(
                cut.cut_id,
                node_id,
                disposition=proof.disposition,
                now_ns=transition_now_ns,
                retry_not_before_ns=(
                    transition_now_ns
                    if proof.disposition is ResearchGraphReconciliationDisposition.RETRY
                    else None
                ),
                failure_type=proof.failure_type,
                failure_message=proof.failure_message,
                failure_provenance=proof.failure_provenance(),
            )
            node_control = self._store.node_control_state(cut.cut_id, node_id)
            if node_control.phase is ResearchGraphNodeControlPhase.RECOVERY_REQUIRED:
                self._store.settle_node_recovery(
                    cut.cut_id,
                    node_id,
                    expected_generation=node_control.generation,
                    now_ns=transition_now_ns,
                )
            proof_rows.append({
                "graph_node_id": node_id,
                "proof_digest": proof.proof_digest,
                "authority_id": proof.authority_id,
                "disposition": proof.disposition.value,
            })

        snapshot = self._store.snapshot(cut.cut_id)
        control = self._store.control_state(cut.cut_id)
        if snapshot.reconciliation_required_node_ids:
            raise RuntimeError(
                "graph-wide reconciliation did not discharge its frozen frontier: "
                f"{snapshot.reconciliation_required_node_ids}"
            )
        if control.phase is ResearchGraphControlPhase.RECOVERY_REQUIRED:
            control = self._store.settle_recovery(
                cut.cut_id,
                expected_generation=control.generation,
                now_ns=time.time_ns(),
            )
            snapshot = self._store.snapshot(cut.cut_id)
        return self._durable_control_receipt(
            request,
            compilation,
            cut,
            active,
            snapshot,
            control,
            state="reconciled",
            extra={
                "reconciled_node_ids": frontier,
                "reconciliation_proofs": tuple(proof_rows),
            },
        )

    def _reconcile(
        self,
        request: ResearchControlRequest,
        portfolio: NoetriumUnit,
    ) -> ResearchControlReceipt:
        if request.payload is not None:
            raise ResearchExecutionUnsupported(
                "RECONCILE never accepts caller-selected recovery disposition"
            )
        if not isinstance(self._runtime, ResearchNodeReconciliationPort):
            raise ResearchExecutionUnsupported(
                "Research execution runtime has no lower-authority reconciliation port"
            )
        if request.target.graph is None:
            return self._reconcile_graph_wide(request, portfolio)

        compilation, cut, active, snapshot, control = self._active_execution_state(
            request,
            portfolio,
        )
        node = self._target_graph_node(request, compilation)
        node_control = self._store.node_control_state(
            cut.cut_id,
            node.graph_node_id,
        )
        global_recovery = (
            control.phase is ResearchGraphControlPhase.RECOVERY_REQUIRED
        )
        local_recovery = (
            node_control.phase is ResearchGraphNodeControlPhase.RECOVERY_REQUIRED
        )
        if not global_recovery and not local_recovery:
            raise ResearchGraphExecutionConflict(
                "RECONCILE requires graph-wide or node-local recovery_required control"
            )
        record = snapshot.node(node.graph_node_id)
        if record.state is not ResearchGraphLiveNodeState.RECONCILE_REQUIRED:
            raise ResearchGraphExecutionConflict(
                "target graph node does not require reconciliation"
            )
        if record.attempt_id is None:
            raise RuntimeError("reconciliation-required node lost attempt identity")

        prepared = prepare_research_execution(
            request.target,
            portfolio,
            self._runtime,
            self._values,
            experiment_compilation=self._experiment_compilation,
            symbol_bindings=self._symbol_bindings,
            artifact_lineage=self._artifact_lineage,
            cut_generation=active.generation,
        )
        if not _same_compilation_identity(prepared.compilation, compilation) or prepared.cut != cut:
            raise ValueError("Research execution reconciliation preflight identity drifted")
        binding = prepared.binding(node.graph_node_id)
        proof = self._runtime.reconcile_node(
            node,
            binding,
            execution_cut_id=cut.cut_id,
            attempt_id=record.attempt_id,
        )
        if type(proof) is not ResearchNodeReconciliationProof:
            raise TypeError("Research execution runtime returned invalid reconciliation proof")
        proof.validate(
            node,
            binding,
            execution_cut_id=cut.cut_id,
            attempt_id=record.attempt_id,
        )

        if proof.disposition is ResearchGraphReconciliationDisposition.SUCCEEDED:
            PreparedResearchNodeExecutor(
                prepared,
                self._runtime,
                self._values,
                artifact_lineage=self._artifact_lineage,
                cost_observation=self._cost_observation,
                diagnostic_degradation=self._diagnostic_degradation,
                failure_materializer=self._failure_materializer,
                lifetime_controller=self._lifetime_controller,
                causal_event_refs=self._causal_event_refs,
            ).publish_recovered_result(node, proof.result)

        transition_now_ns = time.time_ns()
        self._store.resolve_reconciliation(
            cut.cut_id,
            node.graph_node_id,
            disposition=proof.disposition,
            now_ns=transition_now_ns,
            retry_not_before_ns=(
                transition_now_ns
                if proof.disposition is ResearchGraphReconciliationDisposition.RETRY
                else None
            ),
            failure_type=proof.failure_type,
            failure_message=proof.failure_message,
                failure_provenance=proof.failure_provenance(),
        )
        snapshot = self._store.snapshot(cut.cut_id)
        control = self._store.control_state(cut.cut_id)
        settled_node_control = None
        if local_recovery:
            settled_node_control = self._store.settle_node_recovery(
                cut.cut_id,
                node.graph_node_id,
                expected_generation=node_control.generation,
                now_ns=transition_now_ns,
            )
        if global_recovery and not snapshot.reconciliation_required_node_ids:
            control = self._store.settle_recovery(
                cut.cut_id,
                expected_generation=control.generation,
                now_ns=time.time_ns(),
            )
            snapshot = self._store.snapshot(cut.cut_id)
        return self._durable_control_receipt(
            request,
            compilation,
            cut,
            active,
            snapshot,
            control,
            extra={
                "reconciliation_proof_digest": proof.proof_digest,
                "reconciliation_authority_id": proof.authority_id,
                "reconciliation_disposition": proof.disposition.value,
                "node_control_phase": (
                    None
                    if settled_node_control is None
                    else settled_node_control.phase.value
                ),
            },
        )

    def _checkpoint(
        self,
        request: ResearchControlRequest,
        portfolio: NoetriumUnit,
    ) -> ResearchControlReceipt:
        if request.payload is not None:
            raise ResearchExecutionUnsupported(
                "CHECKPOINT does not accept opaque control payload"
            )
        compilation, cut, active, snapshot, control = self._active_execution_state(
            request,
            portfolio,
        )
        if control.phase not in {
            ResearchGraphControlPhase.ACTIVE,
            ResearchGraphControlPhase.PAUSED,
        }:
            raise ResearchGraphExecutionConflict(
                "graph checkpoint requires active or paused durable control, "
                f"actual={control.phase.value}"
            )
        if snapshot.reconciliation_required_node_ids:
            raise ResearchGraphExecutionConflict(
                "graph checkpoint is blocked by reconciliation debt: "
                f"{snapshot.reconciliation_required_node_ids}"
            )

        selected_nodes = (
            compilation.bindings
            if request.target.graph is None
            else (self._target_graph_node(request, compilation),)
        )

        selected_ids = {node.graph_node_id for node in selected_nodes}
        active_nodes = tuple(
            node.node_id
            for node in snapshot.nodes
            if node.node_id in selected_ids
            and node.state in {
                ResearchGraphLiveNodeState.CLAIMED,
                ResearchGraphLiveNodeState.RUNNING,
            }
        )
        if active_nodes:
            raise ResearchGraphExecutionConflict(
                "graph checkpoint requires checkpoint-safe selected nodes; "
                f"active_nodes={active_nodes}"
            )

        succeeded_ids = tuple(
            sorted(
                node.node_id
                for node in snapshot.nodes
                if node.node_id in selected_ids
                and node.state is ResearchGraphLiveNodeState.SUCCEEDED
            )
        )
        bound = {}
        if succeeded_ids:
            if not isinstance(self._runtime, ResearchNodeCheckpointPort):
                raise ResearchExecutionUnsupported(
                    "successful node checkpoint requires lower Machine checkpoint proof"
                )
            checkpoint_bindings = compile_research_execution_bindings(
                compilation,
                experiment_compilation=self._experiment_compilation,
                symbol_bindings=self._symbol_bindings,
                selected_node_ids=succeeded_ids,
            )
            bound = {
                row.graph_node_id: row for row in checkpoint_bindings
            }

        rows = []
        compiled_by_id = {
            node.graph_node_id: node for node in compilation.bindings
        }
        for record in snapshot.nodes:
            if record.node_id not in selected_ids:
                continue
            row: JsonObject = {
                "graph_node_id": record.node_id,
                "semantic_digest": record.semantic_digest,
                "state": record.state.value,
                "attempt_number": record.attempt_number,
            }
            if record.state is ResearchGraphLiveNodeState.SUCCEEDED:
                node = compiled_by_id[record.node_id]
                binding = bound[record.node_id]
                attempt = self._store.attempt_state(
                    cut.cut_id,
                    record.node_id,
                    record.attempt_number,
                )
                proof = self._runtime.checkpoint_node(
                    node,
                    binding,
                    execution_cut_id=cut.cut_id,
                    attempt_id=attempt.attempt_id,
                )
                if type(proof) is not ResearchNodeCheckpointProof:
                    raise TypeError(
                        "Research execution runtime returned invalid node checkpoint proof"
                    )
                proof.validate(
                    node,
                    binding,
                    execution_cut_id=cut.cut_id,
                )
                row.update(
                    {
                        "authority_id": proof.authority_id,
                        "machine_cut_digest": proof.machine_cut.cut_digest,
                        "machine_revision": proof.machine_cut.revision,
                        "machine_commit_id": proof.machine_cut.commit_id,
                        "checkpoint_proof_digest": proof.proof_digest,
                    }
                )
            elif record.state is ResearchGraphLiveNodeState.REUSED:
                reuse = self._store.reuse_record(cut.cut_id, record.node_id)
                if reuse is None:
                    raise RuntimeError("reused graph node lost immutable reuse proof")
                row.update(
                    {
                        "authority_id": "research-graph-reuse",
                        "source_execution_id": reuse.source_execution_id,
                        "source_node_id": reuse.source_node_id,
                        "checkpoint_proof_digest": reuse.proof_digest,
                    }
                )
            else:
                row.update(
                    {
                        "authority_id": "research-graph",
                        "checkpoint_proof_digest": canonical_digest(
                            {
                                "cut_id": cut.cut_id,
                                "graph_node_id": record.node_id,
                                "semantic_digest": record.semantic_digest,
                                "state": record.state.value,
                                "attempt_number": record.attempt_number,
                                "failure_type": record.failure_type,
                                "failure_message": record.failure_message,
                                "blocked_by_node_ids": record.blocked_by_node_ids,
                            }
                        ),
                    }
                )
            rows.append(row)

        if self._checkpoints is None:
            raise ResearchExecutionUnsupported(
                "graph checkpoint requires durable ResearchGraphCheckpointStorePort"
            )
        checkpoint = ResearchGraphCheckpoint(
            execution_cut_id=cut.cut_id,
            graph_digest=compilation.graph_digest,
            research_revision_digest=compilation.research_revision_digest,
            snapshot_generation=snapshot.generation,
            control_generation=control.generation,
            control_phase=control.phase.value,
            selected_node_ids=tuple(sorted(selected_ids)),
            nodes=tuple(rows),
        )
        published = self._checkpoints.publish(checkpoint)
        if published != checkpoint:
            raise RuntimeError(
                "graph checkpoint store changed content-addressed checkpoint"
            )
        return self._durable_control_receipt(
            request,
            compilation,
            cut,
            active,
            snapshot,
            control,
            state="checkpointed",
            extra={
                "checkpoint_digest": checkpoint.checkpoint_digest,
                "checkpoint_scope_digest": checkpoint.scope_digest,
                "checkpoint_durability": self._checkpoints.durability,
                "checkpoint_node_ids": checkpoint.selected_node_ids,
                "checkpoint_nodes": tuple(rows),
            },
        )

    @staticmethod
    def _execution_receipt(
        request: ResearchControlRequest,
        prepared: PreparedResearchExecution,
        active_cut_generation: int,
        report: ResearchGraphExecutionReport,
    ) -> ResearchControlReceipt:
        if report.graph_digest != prepared.compilation.graph_digest:
            raise ValueError("Research execution execution report graph identity drifted")
        if (
            report.research_revision_digest
            != prepared.target.research_revision_digest
        ):
            raise ValueError("Research execution execution report revision identity drifted")
        if report.failed_node_ids:
            state = "failed"
        elif report.blocked_node_ids:
            state = "blocked"
        elif report.cancelled_node_ids:
            state = "cancelled"
        else:
            state = "succeeded"
        payload: JsonObject = {
            "cut_id": prepared.cut.cut_id,
            "preflight_digest": prepared.preflight_digest,
            "selection_digest": prepared.selection_digest,
            "selected_node_ids": prepared.selected_node_ids,
            "graph_digest": report.graph_digest,
            "bindings_digest": prepared.bindings_digest,
            "active_cut_generation": active_cut_generation,
            "succeeded_node_ids": report.succeeded_node_ids,
            "failed_node_ids": report.failed_node_ids,
            "blocked_node_ids": report.blocked_node_ids,
            "cancelled_node_ids": report.cancelled_node_ids,
            "node_results": tuple(
                {
                    "graph_node_id": node.node_id,
                    "semantic_digest": node.semantic_digest,
                    "state": node.state.value,
                    "failure_type": node.failure_type,
                    "failure_message": node.failure_message,
                    "failure_provenance": (
                        None
                        if node.failure_provenance is None
                        else node.failure_provenance.as_payload()
                    ),
                    "blocked_by_node_ids": node.blocked_by_node_ids,
                }
                for node in report.nodes
            ),
        }
        return ResearchControlReceipt(
            request.action,
            request.target,
            state,
            canonical_digest(
                {
                    "action": request.action.value,
                    "target_digest": request.target.target_digest,
                    "state": state,
                    "payload": payload,
                }
            ),
            payload,
        )


__all__ = [
    "PreparedResearchExecution",
    "PreparedResearchNodeExecutor",
    "ResearchExecutionUnsupported",
    "ExecutionNodeFailure",
    "ResearchNodeAdmission",
    "ResearchNodeRuntimePort",
    "ResearchPortfolioRuntimePort",
    "StrictResearchControl",
    "prepare_research_execution",
]
