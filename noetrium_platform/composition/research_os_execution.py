from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
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
)
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphActiveCutStorePort,
    ResearchGraphExecutionConflict,
    ResearchGraphExecutionReport,
    ResearchGraphExecutionStorePort,
    ResearchGraphLiveNodeState,
)

from .research_os import ResearchOSControlPort
from .research_os_experiment import ResearchOSExperimentClosurePort
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
    ResearchOSValueRouter,
    publish_research_os_node_outputs,
    resolve_research_os_node_inputs,
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

        inputs = resolve_research_os_node_inputs(
            self._prepared.cut.cut_id,
            self._prepared.compilation,
            node,
            self._values,
        )
        result = self._runtime.execute(
            context,
            node,
            lowering,
            inputs,
            execution_cut_id=self._prepared.cut.cut_id,
            deadline=deadline,
        )
        publish_research_os_node_outputs(
            self._prepared.cut.cut_id,
            node,
            self._values,
            result,
        )


class StrictResearchOSControl(ResearchOSControlPort):
    """Synchronous fail-closed product control over the durable ResearchGraph."""

    def __init__(
        self,
        execution_store: ResearchGraphExecutionStorePort,
        execution_pool: ResearchExecutionPool,
        runtime: ResearchOSNodeRuntimePort,
        values: ResearchOSValueRouter,
    ) -> None:
        if not isinstance(execution_store, ResearchGraphExecutionStorePort):
            raise TypeError("Research OS control requires graph execution store")
        if not isinstance(execution_store, ResearchGraphActiveCutStorePort):
            raise TypeError("Research OS control requires active-cut CAS store")
        if type(execution_pool) is not ResearchExecutionPool:
            raise TypeError("Research OS control requires explicit execution pool")
        if not isinstance(runtime, ResearchOSNodeRuntimePort):
            raise TypeError("Research OS control requires typed node runtime")
        if type(values) is not ResearchOSValueRouter:
            raise TypeError("Research OS control requires typed value router")
        self._store = execution_store
        self._pool = execution_pool
        self._runtime = runtime
        self._values = values

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
        raise ResearchOSExecutionUnsupported(
            "Research OS control action has no canonical durable implementation yet: "
            f"{request.action.value}"
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
        )
        activation = activate_research_os_execution_cut(
            request.target.execution_id,
            prepared.compilation,
            self._store,
        )
        if activation.cut != prepared.cut:
            raise ValueError("Research OS active cut drifted from preflight cut")

        executor = PreparedResearchOSNodeExecutor(
            prepared,
            self._runtime,
            self._values,
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
            report = scheduler.execute()
        finally:
            scheduler.close()
        return self._execution_receipt(
            request,
            prepared,
            activation.active_cut.generation,
            report,
        )

    def _inspect(
        self,
        request: ResearchControlRequest,
        portfolio: ResearchPortfolio,
    ) -> ResearchControlReceipt:
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
        states = {
            state.value: tuple(
                node.node_id
                for node in snapshot.nodes
                if node.state is state
            )
            for state in ResearchGraphLiveNodeState
        }
        payload: JsonObject = {
            "cut_id": cut.cut_id,
            "graph_digest": compilation.plan.graph_digest,
            "generation": snapshot.generation,
            "active_cut_generation": active.generation,
            "states": states,
        }
        state = (
            "reconciliation_required"
            if snapshot.reconciliation_required_node_ids
            else "durable"
        )
        return ResearchControlReceipt(
            request.action,
            request.target,
            state,
            canonical_digest(
                {
                    "action": request.action.value,
                    "target_digest": request.target.target_digest,
                    "cut_id": cut.cut_id,
                    "snapshot_generation": snapshot.generation,
                    "active_cut_generation": active.generation,
                    "states": states,
                }
            ),
            payload,
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
