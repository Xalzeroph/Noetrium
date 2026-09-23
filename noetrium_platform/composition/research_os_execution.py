from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Protocol, runtime_checkable

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.evidence.artifact.contracts import ArtifactContentIdentity
from noetrium_platform.evidence.artifact.lineage.relation.api import (
    ArtifactLineageEdge,
    ArtifactLineageRelationPort,
)
from noetrium_platform.foundation.kernel.concurrency.api import Deadline
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonObject,
    JsonValue,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.product.research_os import (
    ResearchControlAction,
    ResearchControlReceipt,
    ResearchControlRequest,
    ResearchExecutionTarget,
    ResearchPortfolio,
    ResearchValueKind,
)
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphActiveCutStorePort,
    ResearchGraphControlPhase,
    ResearchGraphControlStorePort,
    ResearchGraphExecutionConflict,
    ResearchGraphExecutionReport,
    ResearchGraphExecutionStorePort,
    ResearchGraphLiveNodeState,
)

from .research_os import ResearchOSControlPort
from .research_os_experiment import ResearchOSExperimentClosurePort
from .research_graph import ResearchGraphControlHalt
from .research_os_graph import (
    CompiledResearchOSGraph,
    CompiledResearchOSGraphNode,
    bind_research_portfolio_scheduler,
    compile_research_portfolio_graph,
)
from .research_os_lowering import (
    LoweredResearchOSGraphNode,
    ResearchOSLoweringPlan,
    compile_research_os_lowering,
)
from .research_os_migration import (
    ResearchOSExecutionCut,
    activate_research_os_execution_cut,
)
from .research_os_values import (
    ResearchOSValueReference,
    ResearchOSValueRouter,
    lookup_research_os_node_input_references,
    publish_research_os_node_outputs,
    validate_research_os_value_authorities,
)


@dataclass(frozen=True, slots=True)
class ResearchOSNodeAdmission:
    """Exact runtime admission for one immutable lowered ResearchGraph node."""

    graph_node_id: str
    semantic_digest: str
    lowering_digest: str
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
            self.lowering_digest,
            "research node admission lowering_digest",
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
                    "lowering_digest": self.lowering_digest,
                    "runtime_binding_digest": self.runtime_binding_digest,
                }
            ),
        )


@runtime_checkable
class ResearchOSNodeRuntimePort(Protocol):
    """Internal L2->L3 runtime boundary; downstream authors never implement this."""

    def admit(
        self,
        node: CompiledResearchOSGraphNode,
        lowering: LoweredResearchOSGraphNode,
    ) -> ResearchOSNodeAdmission: ...

    def execute(
        self,
        context: ExecutionContext,
        node: CompiledResearchOSGraphNode,
        lowering: LoweredResearchOSGraphNode,
        inputs: JsonObject,
        *,
        execution_cut_id: str,
        deadline: Deadline | None,
    ) -> JsonValue: ...


@dataclass(frozen=True, slots=True)
class PreparedResearchOSExecution:
    target: ResearchExecutionTarget
    compilation: CompiledResearchOSGraph
    lowering: ResearchOSLoweringPlan
    cut: ResearchOSExecutionCut
    admissions: tuple[ResearchOSNodeAdmission, ...]
    preflight_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.target) is not ResearchExecutionTarget:
            raise TypeError("prepared research execution target must be typed")
        if type(self.compilation) is not CompiledResearchOSGraph:
            raise TypeError("prepared research execution compilation must be typed")
        if type(self.lowering) is not ResearchOSLoweringPlan:
            raise TypeError("prepared research execution lowering must be typed")
        if type(self.cut) is not ResearchOSExecutionCut:
            raise TypeError("prepared research execution cut must be typed")
        if type(self.admissions) is not tuple or any(
            type(row) is not ResearchOSNodeAdmission
            for row in self.admissions
        ):
            raise TypeError("prepared research execution admissions must be typed")

        ordered = tuple(
            sorted(self.admissions, key=lambda row: row.graph_node_id)
        )
        graph_ids = tuple(node.graph_node_id for node in self.compilation.nodes)
        admission_ids = tuple(row.graph_node_id for row in ordered)
        if admission_ids != graph_ids:
            raise ValueError(
                "prepared research execution admission closure is incomplete"
            )
        if self.compilation.revision != self.target.revision:
            raise ValueError("prepared research execution revision drifted")
        if self.lowering.graph_digest != self.compilation.plan.graph_digest:
            raise ValueError("prepared research execution lowering graph drifted")
        if self.cut.execution_id != self.target.execution_id:
            raise ValueError("prepared research execution logical identity drifted")
        if self.cut.graph_digest != self.compilation.plan.graph_digest:
            raise ValueError("prepared research execution cut graph drifted")
        if (
            self.cut.research_revision_digest
            != self.target.research_revision_digest
        ):
            raise ValueError("prepared research execution cut revision drifted")

        by_id = {
            node.graph_node_id: node
            for node in self.compilation.nodes
        }
        lowered = {
            node.source.graph_node_id: node
            for node in self.lowering.nodes
        }
        for admission in ordered:
            compiled = by_id[admission.graph_node_id]
            lowered_node = lowered[admission.graph_node_id]
            if admission.semantic_digest != compiled.semantic_digest:
                raise ValueError("research node admission semantic identity drifted")
            if admission.lowering_digest != lowered_node.lowering_digest:
                raise ValueError("research node admission lowering identity drifted")

        object.__setattr__(self, "admissions", ordered)
        object.__setattr__(
            self,
            "preflight_digest",
            canonical_digest(
                {
                    "target_digest": self.target.target_digest,
                    "graph_digest": self.compilation.plan.graph_digest,
                    "lowering_digest": self.lowering.lowering_digest,
                    "cut_id": self.cut.cut_id,
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
    ) -> ResearchOSNodeAdmission:
        for row in self.admissions:
            if row.graph_node_id == graph_node_id:
                return row
        raise KeyError(graph_node_id)


class ResearchOSExecutionUnsupported(RuntimeError):
    pass


def prepare_research_os_execution(
    target: ResearchExecutionTarget,
    portfolio: ResearchPortfolio,
    runtime: ResearchOSNodeRuntimePort,
    values: ResearchOSValueRouter,
    *,
    experiment_closures: ResearchOSExperimentClosurePort | None = None,
    artifact_lineage: ArtifactLineageRelationPort | None = None,
) -> PreparedResearchOSExecution:
    """Close the complete execution dependency set before any durable cut exists."""

    if type(target) is not ResearchExecutionTarget:
        raise TypeError("research execution preflight target must be typed")
    if type(portfolio) is not ResearchPortfolio:
        raise TypeError("research execution preflight portfolio must be typed")
    if target.node is not None:
        raise ResearchOSExecutionUnsupported(
            "node-scoped RUN requires canonical subgraph execution semantics"
        )
    if portfolio.portfolio_id != target.portfolio_id:
        raise ValueError("research execution portfolio identity drifted")
    if portfolio.portfolio_digest != target.revision.portfolio_digest:
        raise ValueError("research execution portfolio digest drifted")
    if not isinstance(runtime, ResearchOSNodeRuntimePort):
        raise TypeError("research execution runtime must satisfy ResearchOSNodeRuntimePort")
    if type(values) is not ResearchOSValueRouter:
        raise TypeError("research execution values must be ResearchOSValueRouter")

    compilation = compile_research_portfolio_graph(
        target.revision,
        portfolio,
    )
    lowering = compile_research_os_lowering(
        compilation,
        experiment_closures=experiment_closures,
    )
    validate_research_os_value_authorities(compilation, values)
    requires_artifact_lineage = any(
        output.kind is ResearchValueKind.ARTIFACT
        and any(
            binding.kind is ResearchValueKind.ARTIFACT
            for edge in node.incoming_edges
            for binding in edge.bindings
        )
        for node in compilation.nodes
        for output in node.node.outputs
    )
    if requires_artifact_lineage and artifact_lineage is None:
        raise ResearchOSExecutionUnsupported(
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

    lowered = {
        row.source.graph_node_id: row
        for row in lowering.nodes
    }
    admissions: list[ResearchOSNodeAdmission] = []
    for node in compilation.nodes:
        admission = runtime.admit(node, lowered[node.graph_node_id])
        if type(admission) is not ResearchOSNodeAdmission:
            raise TypeError("research runtime returned invalid node admission")
        if admission.graph_node_id != node.graph_node_id:
            raise ValueError("research runtime admission node identity drifted")
        admissions.append(admission)

    cut = ResearchOSExecutionCut.from_compilation(
        target.execution_id,
        compilation,
    )
    return PreparedResearchOSExecution(
        target,
        compilation,
        lowering,
        cut,
        tuple(admissions),
    )


class PreparedResearchOSNodeExecutor:
    """Scheduler adapter over a preflight-closed runtime/value binding."""

    def __init__(
        self,
        prepared: PreparedResearchOSExecution,
        runtime: ResearchOSNodeRuntimePort,
        values: ResearchOSValueRouter,
        *,
        experiment_closures: ResearchOSExperimentClosurePort | None = None,
        artifact_lineage: ArtifactLineageRelationPort | None = None,
    ) -> None:
        if type(prepared) is not PreparedResearchOSExecution:
            raise TypeError("research node executor requires prepared execution")
        if not isinstance(runtime, ResearchOSNodeRuntimePort):
            raise TypeError("research node executor runtime must satisfy typed port")
        if type(values) is not ResearchOSValueRouter:
            raise TypeError("research node executor values must be typed router")
        self._prepared = prepared
        self._runtime = runtime
        self._values = values
        if experiment_closures is not None and not isinstance(
            experiment_closures,
            ResearchOSExperimentClosurePort,
        ):
            raise TypeError(
                "Research OS control experiment_closures must satisfy "
                "ResearchOSExperimentClosurePort"
            )
        self._experiment_closures = experiment_closures
        if artifact_lineage is not None and not isinstance(
            artifact_lineage,
            ArtifactLineageRelationPort,
        ):
            raise TypeError(
                "research node executor artifact_lineage must satisfy "
                "ArtifactLineageRelationPort"
            )
        self._artifact_lineage = artifact_lineage
        self._lowered = {
            row.source.graph_node_id: row
            for row in prepared.lowering.nodes
        }

    def execute(
        self,
        context: ExecutionContext,
        node: CompiledResearchOSGraphNode,
        *,
        deadline: Deadline | None,
    ) -> None:
        if not isinstance(context, ExecutionContext):
            raise TypeError("research node execution context must be ExecutionContext")
        if type(node) is not CompiledResearchOSGraphNode:
            raise TypeError("research node executor requires compiled graph node")
        admission = self._prepared.admission(node.graph_node_id)
        lowering = self._lowered[node.graph_node_id]
        if admission.semantic_digest != node.semantic_digest:
            raise ValueError("research node execution semantic admission drifted")
        if admission.lowering_digest != lowering.lowering_digest:
            raise ValueError("research node execution lowering admission drifted")

        input_references = lookup_research_os_node_input_references(
            self._prepared.cut.cut_id,
            self._prepared.compilation,
            node,
            self._values,
        )
        inputs: JsonObject = {
            input_name: self._values.resolve(reference)
            for input_name, reference in input_references.items()
        }
        result = self._runtime.execute(
            context,
            node,
            lowering,
            inputs,
            execution_cut_id=self._prepared.cut.cut_id,
            deadline=deadline,
        )
        output_references = publish_research_os_node_outputs(
            self._prepared.cut.cut_id,
            node,
            self._values,
            result,
        )
        self._record_artifact_lineage(
            input_references,
            output_references,
        )

    def _record_artifact_lineage(
        self,
        input_references: dict[str, ResearchOSValueReference],
        output_references: tuple[ResearchOSValueReference, ...],
    ) -> None:
        parents = tuple(
            reference
            for reference in input_references.values()
            if reference.subject.kind is ResearchValueKind.ARTIFACT
        )
        children = tuple(
            reference
            for reference in output_references
            if reference.subject.kind is ResearchValueKind.ARTIFACT
        )
        if not parents or not children:
            return
        if self._artifact_lineage is None:
            raise ResearchOSExecutionUnsupported(
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


class StrictResearchOSControl(ResearchOSControlPort):
    """Synchronous fail-closed product control over the durable ResearchGraph.

    Research OS owns orchestration intent only. Lower Machine/Run/effect/checkpoint
    authorities remain the sole truth for domain execution and external effects.
    """

    def __init__(
        self,
        execution_store: ResearchGraphExecutionStorePort,
        execution_pool: ResearchExecutionPool,
        runtime: ResearchOSNodeRuntimePort,
        values: ResearchOSValueRouter,
        *,
        experiment_closures: ResearchOSExperimentClosurePort | None = None,
        artifact_lineage: ArtifactLineageRelationPort | None = None,
    ) -> None:
        if not isinstance(execution_store, ResearchGraphExecutionStorePort):
            raise TypeError("Research OS control requires graph execution store")
        if not isinstance(execution_store, ResearchGraphActiveCutStorePort):
            raise TypeError("Research OS control requires active-cut CAS store")
        if not isinstance(execution_store, ResearchGraphControlStorePort):
            raise TypeError("Research OS control requires durable graph control store")
        if type(execution_pool) is not ResearchExecutionPool:
            raise TypeError("Research OS control requires explicit execution pool")
        if not isinstance(runtime, ResearchOSNodeRuntimePort):
            raise TypeError("Research OS control requires typed node runtime")
        if type(values) is not ResearchOSValueRouter:
            raise TypeError("Research OS control requires typed value router")
        if experiment_closures is not None and not isinstance(
            experiment_closures,
            ResearchOSExperimentClosurePort,
        ):
            raise TypeError(
                "Research OS control experiment_closures must satisfy "
                "ResearchOSExperimentClosurePort"
            )
        self._store = execution_store
        self._pool = execution_pool
        self._runtime = runtime
        self._values = values
        self._experiment_closures = experiment_closures
        if artifact_lineage is not None and not isinstance(
            artifact_lineage,
            ArtifactLineageRelationPort,
        ):
            raise TypeError(
                "Research OS control artifact_lineage must satisfy "
                "ArtifactLineageRelationPort"
            )
        self._artifact_lineage = artifact_lineage

    def control(
        self,
        request: ResearchControlRequest,
        portfolio: ResearchPortfolio,
    ) -> ResearchControlReceipt:
        if type(request) is not ResearchControlRequest:
            raise TypeError("Research OS control request must be typed")
        if type(portfolio) is not ResearchPortfolio:
            raise TypeError("Research OS control portfolio must be typed")
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
            raise ResearchOSExecutionUnsupported(
                "RECONCILE requires a lower-authority effect/execution proof; "
                "Research OS will not accept a caller-supplied disposition as truth"
            )
        raise ResearchOSExecutionUnsupported(
            "Research OS control action has no canonical durable implementation: "
            f"{request.action.value}"
        )

    @staticmethod
    def _require_whole_graph_control(request: ResearchControlRequest) -> None:
        if request.target.node is not None:
            raise ResearchOSExecutionUnsupported(
                f"node-scoped {request.action.value.upper()} requires an exact "
                "lower-runtime control proof and is not inferred from graph state"
            )
        if request.payload is not None:
            raise ResearchOSExecutionUnsupported(
                f"{request.action.value.upper()} does not accept opaque control payload"
            )

    def _active_execution_state(
        self,
        request: ResearchControlRequest,
        portfolio: ResearchPortfolio,
    ):
        compilation = compile_research_portfolio_graph(
            request.target.revision,
            portfolio,
        )
        cut = ResearchOSExecutionCut.from_compilation(
            request.target.execution_id,
            compilation,
        )
        active = self._store.active_cut(request.target.execution_id)
        if active is None:
            raise ResearchGraphExecutionConflict(
                "Research OS execution has no active durable cut"
            )
        if active.cut_id != cut.cut_id:
            raise ResearchGraphExecutionConflict(
                "Research OS target revision is not the active durable cut"
            )
        snapshot = self._store.snapshot(cut.cut_id)
        control = self._store.control_state(cut.cut_id)
        return compilation, cut, active, snapshot, control

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
        compilation: CompiledResearchOSGraph,
        cut: ResearchOSExecutionCut,
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
        payload: JsonObject = {
            "cut_id": cut.cut_id,
            "graph_digest": compilation.plan.graph_digest,
            "generation": snapshot.generation,
            "active_cut_generation": active.generation,
            "control_phase": control.phase.value,
            "control_generation": control.generation,
            "states": states,
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

    def _run(
        self,
        request: ResearchControlRequest,
        portfolio: ResearchPortfolio,
    ) -> ResearchControlReceipt:
        if request.payload is not None:
            raise ResearchOSExecutionUnsupported(
                "RUN payload requires declared root-input semantics; implicit global "
                "payload injection is forbidden"
            )
        prepared = prepare_research_os_execution(
            request.target,
            portfolio,
            self._runtime,
            self._values,
            experiment_closures=self._experiment_closures,
            artifact_lineage=self._artifact_lineage,
        )
        activation = activate_research_os_execution_cut(
            request.target.execution_id,
            prepared.compilation,
            self._store,
        )
        if activation.cut != prepared.cut:
            raise ValueError("Research OS active cut drifted from preflight cut")
        control = self._store.control_state(prepared.cut.cut_id)
        if control.phase is not ResearchGraphControlPhase.ACTIVE:
            raise ResearchGraphExecutionConflict(
                "RUN requires an active graph control phase; use RESUME for a "
                f"paused execution, actual={control.phase.value}"
            )
        return self._drive(
            request,
            prepared,
            activation.active_cut.generation,
        )

    def _drive(
        self,
        request: ResearchControlRequest,
        prepared: PreparedResearchOSExecution,
        active_cut_generation: int,
    ) -> ResearchControlReceipt:
        executor = PreparedResearchOSNodeExecutor(
            prepared,
            self._runtime,
            self._values,
            artifact_lineage=self._artifact_lineage,
        )
        scheduler = bind_research_portfolio_scheduler(
            prepared.compilation,
            executor,
            execution_pool=self._pool,
            execution_store=self._store,
            execution_id=prepared.cut.cut_id,
            task_group_id=(
                "research-os:"
                f"{prepared.target.execution_id}:{prepared.cut.cut_id}"
            ),
        )
        try:
            try:
                report = scheduler.execute()
            except ResearchGraphControlHalt:
                active = self._store.active_cut(request.target.execution_id)
                if active is None or active.cut_id != prepared.cut.cut_id:
                    raise ResearchGraphExecutionConflict(
                        "Research OS active cut changed while control halt was observed"
                    )
                snapshot = self._store.snapshot(prepared.cut.cut_id)
                control = self._store.control_state(prepared.cut.cut_id)
                return self._durable_control_receipt(
                    request,
                    prepared.compilation,
                    prepared.cut,
                    active,
                    snapshot,
                    control,
                )
        finally:
            scheduler.close()
        return self._execution_receipt(
            request,
            prepared,
            active_cut_generation,
            report,
        )

    def _inspect(
        self,
        request: ResearchControlRequest,
        portfolio: ResearchPortfolio,
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
        portfolio: ResearchPortfolio,
    ) -> ResearchControlReceipt:
        self._require_whole_graph_control(request)
        compilation, cut, active, snapshot, control = self._active_execution_state(
            request,
            portfolio,
        )
        control = self._store.request_drain(
            cut.cut_id,
            expected_generation=control.generation,
            now_ns=time.time_ns(),
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
        )

    def _pause(
        self,
        request: ResearchControlRequest,
        portfolio: ResearchPortfolio,
    ) -> ResearchControlReceipt:
        self._require_whole_graph_control(request)
        compilation, cut, active, _snapshot, control = self._active_execution_state(
            request,
            portfolio,
        )
        control = self._store.pause_if_quiescent(
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
            state="paused",
        )

    def _interrupt(
        self,
        request: ResearchControlRequest,
        portfolio: ResearchPortfolio,
    ) -> ResearchControlReceipt:
        self._require_whole_graph_control(request)
        compilation, cut, active, _snapshot, control = self._active_execution_state(
            request,
            portfolio,
        )
        control = self._store.interrupt(
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
        )

    def _resume(
        self,
        request: ResearchControlRequest,
        portfolio: ResearchPortfolio,
    ) -> ResearchControlReceipt:
        self._require_whole_graph_control(request)
        compilation, cut, active, _snapshot, control = self._active_execution_state(
            request,
            portfolio,
        )
        control = self._store.resume(
            cut.cut_id,
            expected_generation=control.generation,
            now_ns=time.time_ns(),
        )
        if control.phase is not ResearchGraphControlPhase.ACTIVE:
            raise ResearchGraphExecutionConflict(
                "Research OS resume did not produce active graph control"
            )
        prepared = prepare_research_os_execution(
            request.target,
            portfolio,
            self._runtime,
            self._values,
            experiment_closures=self._experiment_closures,
            artifact_lineage=self._artifact_lineage,
        )
        if prepared.compilation != compilation or prepared.cut != cut:
            raise ValueError("Research OS resume preflight identity drifted")
        return self._drive(request, prepared, active.generation)

    def _cancel(
        self,
        request: ResearchControlRequest,
        portfolio: ResearchPortfolio,
    ) -> ResearchControlReceipt:
        self._require_whole_graph_control(request)
        compilation, cut, active, _snapshot, control = self._active_execution_state(
            request,
            portfolio,
        )
        control = self._store.cancel_if_quiescent(
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
            state="cancelled",
        )

    @staticmethod
    def _retry_descendants(
        compilation: CompiledResearchOSGraph,
        root_node_id: str,
    ) -> tuple[str, ...]:
        dependents: dict[str, list[str]] = {
            node.graph_node_id: [] for node in compilation.nodes
        }
        for node in compilation.plan.nodes:
            for dependency in node.depends_on_node_ids:
                dependents[dependency].append(node.node_id)
        seen: set[str] = set()
        frontier = list(dependents[root_node_id])
        while frontier:
            node_id = frontier.pop()
            if node_id in seen:
                continue
            seen.add(node_id)
            frontier.extend(dependents[node_id])
        return tuple(sorted(seen))

    def _retry(
        self,
        request: ResearchControlRequest,
        portfolio: ResearchPortfolio,
    ) -> ResearchControlReceipt:
        if request.payload is not None:
            raise ResearchOSExecutionUnsupported(
                "RETRY does not accept an opaque retry policy payload"
            )
        if request.target.node is None:
            raise ResearchOSExecutionUnsupported(
                "RETRY requires an explicit ResearchNodeRef; whole-graph retry "
                "would hide the failed scientific boundary"
            )
        compilation, cut, active, _snapshot, control = self._active_execution_state(
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
        matches = tuple(
            node
            for node in compilation.nodes
            if node.ref == request.target.node
        )
        if len(matches) != 1:
            raise ResearchGraphExecutionConflict(
                "retry target does not identify exactly one compiled graph node"
            )
        root = matches[0]
        descendants = self._retry_descendants(
            compilation,
            root.graph_node_id,
        )
        self._store.retry_failed_subgraph(
            cut.cut_id,
            root.graph_node_id,
            descendant_node_ids=descendants,
            retry_not_before_ns=time.time_ns(),
        )
        if control.phase is ResearchGraphControlPhase.PAUSED:
            control = self._store.resume(
                cut.cut_id,
                expected_generation=control.generation,
                now_ns=time.time_ns(),
            )
        prepared = prepare_research_os_execution(
            request.target,
            portfolio,
            self._runtime,
            self._values,
            experiment_closures=self._experiment_closures,
            artifact_lineage=self._artifact_lineage,
        )
        if prepared.compilation != compilation or prepared.cut != cut:
            raise ValueError("Research OS retry preflight identity drifted")
        return self._drive(request, prepared, active.generation)

    def _checkpoint(
        self,
        request: ResearchControlRequest,
        portfolio: ResearchPortfolio,
    ) -> ResearchControlReceipt:
        self._require_whole_graph_control(request)
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
        active_nodes = tuple(
            node.node_id
            for node in snapshot.nodes
            if node.state in {
                ResearchGraphLiveNodeState.CLAIMED,
                ResearchGraphLiveNodeState.RUNNING,
            }
        )
        if active_nodes:
            raise ResearchGraphExecutionConflict(
                "graph checkpoint requires a quiescent cut or exact lower "
                f"checkpoint proofs; active_nodes={active_nodes}"
            )
        if snapshot.reconciliation_required_node_ids:
            raise ResearchGraphExecutionConflict(
                "graph checkpoint is blocked by reconciliation debt: "
                f"{snapshot.reconciliation_required_node_ids}"
            )
        checkpoint_digest = canonical_digest(
            {
                "schema": "noetrium.research-graph-checkpoint.v1",
                "cut_id": cut.cut_id,
                "graph_digest": compilation.plan.graph_digest,
                "research_revision_digest": (
                    compilation.plan.research_revision_digest
                ),
                "snapshot_generation": snapshot.generation,
                "control_generation": control.generation,
                "control_phase": control.phase.value,
                "states": self._states(snapshot),
            }
        )
        return self._durable_control_receipt(
            request,
            compilation,
            cut,
            active,
            snapshot,
            control,
            state="checkpointed",
            extra={"checkpoint_digest": checkpoint_digest},
        )

    @staticmethod
    def _execution_receipt(
        request: ResearchControlRequest,
        prepared: PreparedResearchOSExecution,
        active_cut_generation: int,
        report: ResearchGraphExecutionReport,
    ) -> ResearchControlReceipt:
        if report.graph_digest != prepared.compilation.plan.graph_digest:
            raise ValueError("Research OS execution report graph identity drifted")
        if (
            report.research_revision_digest
            != prepared.target.research_revision_digest
        ):
            raise ValueError("Research OS execution report revision identity drifted")
        if report.failed_node_ids:
            state = "failed"
        elif report.blocked_node_ids:
            state = "blocked"
        else:
            state = "succeeded"
        payload: JsonObject = {
            "cut_id": prepared.cut.cut_id,
            "preflight_digest": prepared.preflight_digest,
            "graph_digest": report.graph_digest,
            "lowering_digest": prepared.lowering.lowering_digest,
            "active_cut_generation": active_cut_generation,
            "succeeded_node_ids": report.succeeded_node_ids,
            "failed_node_ids": report.failed_node_ids,
            "blocked_node_ids": report.blocked_node_ids,
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
    "PreparedResearchOSExecution",
    "PreparedResearchOSNodeExecutor",
    "ResearchOSExecutionUnsupported",
    "ResearchOSNodeAdmission",
    "ResearchOSNodeRuntimePort",
    "StrictResearchOSControl",
    "prepare_research_os_execution",
]
