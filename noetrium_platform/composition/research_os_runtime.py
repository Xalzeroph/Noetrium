from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, replace
from pathlib import Path
from threading import RLock

from noetrium_platform.composition.method_runtime import (
    bind_standard_method_runtime,
    standard_method_runtime_binder,
)
from noetrium_platform.foundation.kernel.concurrency.api import Deadline, TaskContextPort
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.shared_host_pressure import (
    ResourceCompetitionDemand,
    StorageCompetitionDemand,
)
from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineJournal,
    ExecutionContext,
    JsonObject,
    JsonValue,
    MachineCut,
    MachineStatus,
    canonical_bytes,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.research.execution.machines import ResearchProgramHost
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphReconciliationDisposition,
)
from noetrium_platform.research.experimentation.api import (
    ExperimentProgramBinding,
    experiment_report_from_data,
)
from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactRetention,
)
from noetrium_platform.evidence.artifact.reference.api import ArtifactReference
from noetrium_platform.foundation.governance.api import ScopeIdentity, ScopeKind
from .research_execution_content import ResearchExecutionContentAuthorities
from noetrium_platform.product.research_os import (
    ResearchMethodImplementation,
    ResearchValueKind,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodObservationPort,
    MethodRunStatus,
    MethodRuntimeBindingPlan,
    MethodRuntimeContext,
    MethodRuntimePortInventory,
    plan_method_runtime_binding,
)
from noetrium_platform.research.execution.workflow.runtime import (
    execute_bound_method_program,
)

from .research_os_checkpoint import (
    ResearchOSCheckpointIndeterminate,
    ResearchOSNodeCheckpointProof,
)
from .research_os_experiment import (
    ResearchOSExperimentRuntimeBinding,
    ResearchOSExperimentRuntimeBindingPort,
    ResearchOSScientificInputBoundStudyExecutionPort,
)
from .research_os_execution import (
    ResearchOSNodeAdmission,
    ResearchOSNodeRuntimePort,
    ResearchOSPortfolioRuntimePort,
)
from .research_os_graph import CompiledResearchOSGraph, CompiledResearchOSGraphNode
from .research_child_machine_runtime import (
    compose_program_method_runtime_inventory,
)
from .research_os_lowering import (
    LoweredResearchOSGraphNode,
    ResearchOSLoweringTarget,
)
from .research_os_scientific_analysis import (
    materialize_research_scientific_inputs,
)
from .research_os_reconciliation import (
    ResearchOSNodeReconciliationProof,
    ResearchOSReconciliationIndeterminate,
)


class CanonicalResearchOSRuntimeUnsupported(RuntimeError):
    pass


class CanonicalResearchOSRuntimeFailure(RuntimeError):
    def __init__(self, message: str, *, failure_id: str | None = None) -> None:
        self.failure_id = failure_id
        super().__init__(message)


class CanonicalResearchOSNodeRuntime(
    ResearchOSNodeRuntimePort,
    ResearchOSPortfolioRuntimePort,
):
    """Built-in strict runtime for already unambiguous Machine lowerings.

    Experiment-family nodes are intentionally rejected until their top-level
    semantics lower to the existing ExperimentProgram/Trial authorities.
    """

    _MACHINE_TARGETS = frozenset(
        {
            ResearchOSLoweringTarget.RUN_MACHINE,
            ResearchOSLoweringTarget.EVALUATION_MACHINE,
            ResearchOSLoweringTarget.OPTIMIZATION_MACHINE,
            ResearchOSLoweringTarget.ANALYSIS_MACHINE,
            ResearchOSLoweringTarget.PUBLICATION_MACHINE,
            ResearchOSLoweringTarget.CUSTOM_MACHINE,
        }
    )

    def __init__(
        self,
        state_root: str | Path,
        *,
        execution_pool: ResearchExecutionPool | None = None,
        experiment_bindings: ResearchOSExperimentRuntimeBindingPort | None = None,
        method_runtime_inventory: MethodRuntimePortInventory | None = None,
        operation_dispatcher: OperationDispatchPort | None = None,
        method_observation: MethodObservationPort | None = None,
        content_authorities: ResearchExecutionContentAuthorities,
        max_steps: int | None = None,
    ) -> None:
        if not isinstance(state_root, (str, Path)):
            raise TypeError("canonical Research OS runtime state_root is required")
        root = Path(state_root).absolute()
        if root.exists() and not root.is_dir():
            raise ValueError("canonical Research OS runtime state_root must be a directory")
        if max_steps is not None and (type(max_steps) is not int or max_steps < 1):
            raise ValueError("canonical Research OS runtime max_steps must be positive or None")
        if (execution_pool is None) != (experiment_bindings is None):
            raise ValueError(
                "canonical Experiment runtime requires both execution_pool and "
                "experiment_bindings"
            )
        if execution_pool is not None and type(execution_pool) is not ResearchExecutionPool:
            raise TypeError(
                "canonical Experiment runtime execution_pool must be ResearchExecutionPool"
            )
        if experiment_bindings is not None and not isinstance(
            experiment_bindings,
            ResearchOSExperimentRuntimeBindingPort,
        ):
            raise TypeError(
                "canonical Experiment runtime binding resolver must satisfy "
                "ResearchOSExperimentRuntimeBindingPort"
            )
        if method_runtime_inventory is not None and not isinstance(
            method_runtime_inventory,
            MethodRuntimePortInventory,
        ):
            raise TypeError(
                "canonical Method runtime inventory must be MethodRuntimePortInventory"
            )
        if type(content_authorities) is not ResearchExecutionContentAuthorities:
            raise TypeError(
                "canonical Research OS runtime requires ResearchExecutionContentAuthorities"
            )
        root.mkdir(parents=True, exist_ok=True)
        self._state_root = root
        self._execution_pool = execution_pool
        self._experiment_bindings = experiment_bindings
        self._method_runtime_inventory = (
            MethodRuntimePortInventory()
            if method_runtime_inventory is None
            else method_runtime_inventory
        )
        self._max_steps = max_steps
        self._operation_dispatcher = operation_dispatcher
        self._method_observation = method_observation
        self._content = content_authorities
        self._machine_journal = DirectoryMachineJournal(root / "program-journal")
        self._method_journal = DirectoryMachineJournal(root / "method-state" / "journal")
        self._method_binder_digest = standard_method_runtime_binder().identity_digest
        self._program_method_runtime_inventories: dict[
            tuple[str, str],
            MethodRuntimePortInventory,
        ] = {}
        self._method_runtime_binding_plans: dict[
            tuple[str, str],
            MethodRuntimeBindingPlan,
        ] = {}
        self._method_inventory_lock = RLock()

    def bind_portfolio(self, compilation: CompiledResearchOSGraph) -> None:
        if type(compilation) is not CompiledResearchOSGraph:
            raise TypeError(
                "canonical Research OS portfolio binding requires compiled graph"
            )
        staged: dict[tuple[str, str], MethodRuntimePortInventory] = {}
        nodes_by_program: dict[str, list[CompiledResearchOSGraphNode]] = {}
        for node in compilation.nodes:
            nodes_by_program.setdefault(node.ref.program_id, []).append(node)
        for program in compilation.portfolio._programs:
            for node in nodes_by_program.get(program.program_id, ()):
                method_program_digests = tuple(
                    definition.implementation.resolve().program.program_digest
                    for definition in node.definitions
                    if type(definition.implementation) is ResearchMethodImplementation
                )
                # Only a METHOD_MACHINE node consumes a Method runtime inventory and
                # canonical lowering already requires exactly one MethodProgram there.
                # Multi-Method experiment nodes intentionally receive no Method-owned
                # child hosts; their participant bindings compose the selected Method
                # independently at Trial execution time.
                selected = (
                    method_program_digests
                    if len(method_program_digests) <= 1
                    else ()
                )
                inventory = compose_program_method_runtime_inventory(
                    program,
                    self._method_runtime_inventory,
                    method_program_digests=selected,
                    journal=self._machine_journal,
                    max_steps=self._max_steps,
                )
                staged[(program.program_id, node.semantic_digest)] = inventory

        with self._method_inventory_lock:
            for key, inventory in staged.items():
                current = self._program_method_runtime_inventories.get(key)
                if (
                    current is not None
                    and current.identity_digest != inventory.identity_digest
                ):
                    raise ValueError(
                        "program-scoped Method runtime inventory identity drifted: "
                        f"program_id={key[0]!r} semantic_digest={key[1]}"
                    )
            self._program_method_runtime_inventories.update(staged)

    def _method_inventory_for(
        self,
        node: CompiledResearchOSGraphNode,
    ) -> MethodRuntimePortInventory:
        key = (node.ref.program_id, node.semantic_digest)
        with self._method_inventory_lock:
            return self._program_method_runtime_inventories.get(
                key,
                self._method_runtime_inventory,
            )

    def _method_binding_plan_for(
        self,
        program,
        inventory: MethodRuntimePortInventory,
    ) -> MethodRuntimeBindingPlan:
        key = (program.program_digest, inventory.identity_digest)
        with self._method_inventory_lock:
            cached = self._method_runtime_binding_plans.get(key)
            if cached is not None:
                return cached
            plan = plan_method_runtime_binding(program, inventory)
            current = self._method_runtime_binding_plans.get(key)
            if current is not None:
                if current.digest != plan.digest:
                    raise RuntimeError(
                        "Method runtime binding plan identity drifted for immutable inputs"
                    )
                return current
            self._method_runtime_binding_plans[key] = plan
            return plan

    @staticmethod
    def _experiment_admission_binding_digest(
        lowering: LoweredResearchOSGraphNode,
        runtime_binding: ResearchOSExperimentRuntimeBinding,
    ) -> str:
        closure = lowering.experiment_closure
        if closure is None:
            raise CanonicalResearchOSRuntimeUnsupported(
                "Experimentation target has no canonical experiment closure"
            )
        runtime_binding.validate_closure(closure)
        return canonical_digest(
            {
                "runtime": "canonical-research-os-experiment-runtime",
                "version": 1,
                "closure_digest": closure.closure_digest,
                "runtime_binding_digest": runtime_binding.runtime_binding_digest,
                "experiment_program_digest": (
                    closure.experiment_program.program.program_digest
                ),
                "experiment_batch_plan_digest": (
                    closure.experiment_program.batch_plan_digest
                ),
                "platform_definition_bindings": tuple(
                    row.binding_digest for row in lowering.platform_bindings
                ),
                "journal": "directory-machine-journal",
            }
        )

    def admit(
        self,
        node: CompiledResearchOSGraphNode,
        lowering: LoweredResearchOSGraphNode,
    ) -> ResearchOSNodeAdmission:
        if type(node) is not CompiledResearchOSGraphNode:
            raise TypeError("canonical Research OS runtime requires compiled node")
        if type(lowering) is not LoweredResearchOSGraphNode:
            raise TypeError("canonical Research OS runtime requires lowered node")
        if lowering.source != node:
            raise ValueError("canonical Research OS runtime node/lowering identity drifted")
        if lowering.target is ResearchOSLoweringTarget.EXPERIMENTATION:
            closure = lowering.experiment_closure
            if closure is None:
                raise CanonicalResearchOSRuntimeUnsupported(
                    "Experimentation target has no canonical experiment closure"
                )
            if node.node.outputs and (
                len(node.node.outputs) != 1
                or node.node.outputs[0].kind is not ResearchValueKind.ARTIFACT
            ):
                raise CanonicalResearchOSRuntimeUnsupported(
                    "Experimentation may expose only one ARTIFACT report output"
                )
            if self._execution_pool is None or self._experiment_bindings is None:
                raise CanonicalResearchOSRuntimeUnsupported(
                    "canonical Experiment execution requires exact runtime binding "
                    "and explicit ResearchExecutionPool"
                )
            runtime_binding = self._experiment_bindings.resolve(closure)
            if type(runtime_binding) is not ResearchOSExperimentRuntimeBinding:
                raise TypeError(
                    "experiment runtime binding resolver returned invalid binding"
                )
            binding_digest = self._experiment_admission_binding_digest(
                lowering,
                runtime_binding,
            )
            return ResearchOSNodeAdmission(
                node.graph_node_id,
                node.semantic_digest,
                lowering.lowering_digest,
                binding_digest,
            )

        if lowering.platform_requirements:
            raise CanonicalResearchOSRuntimeUnsupported(
                "canonical Research OS runtime received unresolved platform requirements: "
                f"node={node.graph_node_id} requirements="
                f"{tuple(row.definition_id for row in lowering.platform_requirements)}"
            )

        if lowering.target is ResearchOSLoweringTarget.METHOD_MACHINE:
            if len(lowering.method_programs) != 1 or lowering.machine_programs:
                raise CanonicalResearchOSRuntimeUnsupported(
                    "METHOD node must lower to exactly one MethodProgram"
                )
            program = lowering.method_programs[0].program
            inventory = self._method_inventory_for(node)
            binding_plan = self._method_binding_plan_for(
                program,
                inventory,
            )
            try:
                binding_plan.require_complete()
            except RuntimeError as exc:
                raise CanonicalResearchOSRuntimeUnsupported(
                    "canonical Method runtime binding is incomplete: "
                    f"node={node.graph_node_id} details={exc}"
                ) from exc
            binding_digest = canonical_digest(
                {
                    "runtime": "canonical-research-os-node-runtime",
                    "version": 2,
                    "target": lowering.target.value,
                    "program_digest": program.program_digest,
                    "method_runtime_binder_digest": self._method_binder_digest,
                    "method_runtime_inventory_digest": (
                        inventory.identity_digest
                    ),
                    "method_runtime_binding_plan_digest": binding_plan.digest,
                    "platform_definition_bindings": tuple(
                        row.binding_digest for row in lowering.platform_bindings
                    ),
                    "journal": "directory-machine-journal",
                    "max_steps": self._max_steps,
                }
            )
            return ResearchOSNodeAdmission(
                node.graph_node_id,
                node.semantic_digest,
                lowering.lowering_digest,
                binding_digest,
            )

        if lowering.target in self._MACHINE_TARGETS:
            if lowering.method_programs or len(lowering.machine_programs) != 1:
                raise CanonicalResearchOSRuntimeUnsupported(
                    "non-Method node must lower to exactly one ResearchProgram"
                )
            lowered = lowering.machine_programs[0]
            if lowered.program.required_capabilities:
                raise CanonicalResearchOSRuntimeUnsupported(
                    "canonical pure ResearchProgram runtime cannot satisfy external "
                    "capabilities"
                )
            binding_digest = canonical_digest(
                {
                    "runtime": "canonical-research-os-node-runtime",
                    "version": 1,
                    "target": lowering.target.value,
                    "program_digest": lowered.program.program_digest,
                    "operations_digest": lowered.operations_digest,
                    "platform_definition_bindings": tuple(
                        row.binding_digest for row in lowering.platform_bindings
                    ),
                    "journal": "directory-machine-journal",
                    "max_steps": self._max_steps,
                }
            )
            return ResearchOSNodeAdmission(
                node.graph_node_id,
                node.semantic_digest,
                lowering.lowering_digest,
                binding_digest,
            )

        raise CanonicalResearchOSRuntimeUnsupported(
            "Research OS node target has no canonical built-in runtime yet: "
            f"node={node.graph_node_id} target={lowering.target.value}"
        )

    def execute(
        self,
        context: ExecutionContext,
        task_context: TaskContextPort,
        node: CompiledResearchOSGraphNode,
        lowering: LoweredResearchOSGraphNode,
        inputs: JsonObject,
        *,
        execution_cut_id: str,
        deadline: Deadline | None,
    ) -> JsonValue:
        if not isinstance(context, ExecutionContext):
            raise TypeError("canonical Research OS runtime requires ExecutionContext")
        task_context.checkpoint()
        if type(inputs) is not dict:
            raise TypeError("canonical Research OS runtime inputs must be JsonObject")
        require_sha256(execution_cut_id, "canonical Research OS execution_cut_id")
        if deadline is not None and deadline.expired:
            raise CanonicalResearchOSRuntimeFailure(
                "canonical Research OS node deadline expired before execution"
            )

        admission = self.admit(node, lowering)
        runtime_context = replace(
            context,
            component_id=node.graph_node_id,
        )
        payload: JsonValue = inputs if inputs else None
        scientific_projection = any(
            isinstance(definition.config, Mapping)
            and (
                definition.config.get("analysis_engine") in {"workbench", "custom"}
                or definition.config.get("metric_engine") == "study_measurement"
            )
            for definition in lowering.source.definitions
        )
        if scientific_projection:
            payload = materialize_research_scientific_inputs(
                payload,
                self._content,
            )
        machine_id = self._machine_id(
            context.run_id,
            node.graph_node_id,
            lowering.lowering_digest,
        )

        if lowering.target is ResearchOSLoweringTarget.EXPERIMENTATION:
            return self._execute_experiment(
                machine_id,
                lowering,
                admission.runtime_binding_digest,
                scientific_inputs=inputs,
                execution_cut_id=execution_cut_id,
                execution_id=context.run_id,
                execution_tenant_id=context.execution_tenant_id,
                deadline=deadline,
            )
        if lowering.target is ResearchOSLoweringTarget.METHOD_MACHINE:
            return self._execute_method(
                runtime_context,
                machine_id,
                node,
                lowering,
                payload,
                admission.runtime_binding_digest,
            )
        if lowering.target in self._MACHINE_TARGETS:
            return self._execute_program(
                runtime_context,
                machine_id,
                lowering,
                payload,
                admission.runtime_binding_digest,
            )
        raise CanonicalResearchOSRuntimeUnsupported(
            "canonical runtime execution target was not admitted"
        )

    def _artifact_reference_json(
        self,
        reference: ArtifactReference,
    ) -> JsonObject:
        if type(reference) is not ArtifactReference:
            raise TypeError("Experiment report requires ArtifactReference")
        record = self._content.artifacts.get(reference.artifact_id)
        return {
            "reference_id": reference.reference_id,
            "scope_kind": reference.scope.kind.value,
            "scope_id": reference.scope.scope_id,
            "artifact_id": reference.artifact_id,
            "generation": reference.generation,
            "content_sha256": record.digest,
            "media_type": record.media_type,
            "artifact_kind": record.kind.value,
            "retention": record.retention.value,
        }

    def _publish_exact_json(
        self,
        *,
        execution_cut_id: str,
        reference_id: str,
        payload: JsonValue,
        kind: ArtifactKind,
        metadata: Mapping[str, str],
    ) -> ArtifactReference:
        require_sha256(execution_cut_id, "Experiment Artifact execution cut")
        body = canonical_bytes(payload, indent=2) + b"\n"
        reference = self._content.publish(
            reference_id=reference_id,
            scope=ScopeIdentity(ScopeKind.EXECUTION_CUT, execution_cut_id),
            payload=body,
            media_type="application/json",
            kind=kind,
            retention=ArtifactRetention.PROJECT,
            producer_component_id="research-os.experiment-report",
            metadata=metadata,
        )
        if self._content.read(reference) != body:
            raise CanonicalResearchOSRuntimeFailure(
                "canonical Artifact authority returned content drift"
            )
        return reference

    def _publish_experiment_report(
        self,
        lowering: LoweredResearchOSGraphNode,
        runtime_binding: ResearchOSExperimentRuntimeBinding,
        report,
        *,
        execution_cut_id: str,
    ) -> JsonObject:
        closure = lowering.experiment_closure
        if closure is None:
            raise CanonicalResearchOSRuntimeUnsupported(
                "Experiment report publication has no canonical closure"
            )
        runtime_binding.validate_closure(closure)
        prefix = f"experiment:{closure.closure_digest}"
        base_metadata = {
            "closure_digest": closure.closure_digest,
            "execution_cut_id": execution_cut_id,
            "research_plan_digest": closure.research_plan.research_plan_digest,
        }
        protocol = self._publish_exact_json(
            execution_cut_id=execution_cut_id,
            reference_id=f"{prefix}:protocol",
            payload={
                "protocol": asdict(closure.experiment_program.plan.protocol),
                "assignments": tuple(
                    asdict(row)
                    for row in closure.experiment_program.plan.assignments
                ),
            },
            kind=ArtifactKind.SCIENTIFIC,
            metadata={**base_metadata, "report_part": "protocol"},
        )
        observations = self._publish_exact_json(
            execution_cut_id=execution_cut_id,
            reference_id=f"{prefix}:observations",
            payload=tuple(asdict(row) for row in report.observations),
            kind=ArtifactKind.REPORT,
            metadata={**base_metadata, "report_part": "observations"},
        )
        aggregates = self._publish_exact_json(
            execution_cut_id=execution_cut_id,
            reference_id=f"{prefix}:aggregates",
            payload=tuple(asdict(row) for row in report.aggregates),
            kind=ArtifactKind.REPORT,
            metadata={**base_metadata, "report_part": "aggregates"},
        )
        manifest_payload: JsonObject = {
            "schema": "research-os.experiment-report-manifest.v3",
            "closure_digest": closure.closure_digest,
            "execution_cut_id": execution_cut_id,
            "content_authority_digest": self._content.identity_digest,
            "research_plan_digest": closure.research_plan.research_plan_digest,
            "experiment_program_digest": (
                closure.experiment_program.program.program_digest
            ),
            "protocol_digest": report.protocol_digest,
            "binding_digest": report.binding_digest,
            "plan_digest": report.plan_digest,
            "observation_count": len(report.observations),
            "aggregate_count": len(report.aggregates),
            "protocol_artifact": self._artifact_reference_json(protocol),
            "observations_artifact": self._artifact_reference_json(observations),
            "aggregates_artifact": self._artifact_reference_json(aggregates),
        }
        manifest = self._publish_exact_json(
            execution_cut_id=execution_cut_id,
            reference_id=f"{prefix}:report-manifest",
            payload=manifest_payload,
            kind=ArtifactKind.REPORT,
            metadata={**base_metadata, "report_part": "manifest"},
        )
        return {
            "schema": "research-os.experiment-report-ref.v3",
            "closure_digest": closure.closure_digest,
            "execution_cut_id": execution_cut_id,
            "content_authority_digest": self._content.identity_digest,
            "manifest": self._artifact_reference_json(manifest),
        }

    def _execute_experiment(
        self,
        machine_id: str,
        lowering: LoweredResearchOSGraphNode,
        admission_binding_digest: str,
        *,
        scientific_inputs: JsonObject,
        execution_cut_id: str,
        execution_id: str,
        execution_tenant_id: str | None,
        deadline: Deadline | None,
    ) -> JsonValue:
        closure = lowering.experiment_closure
        if closure is None:
            raise CanonicalResearchOSRuntimeUnsupported(
                "Experimentation execution has no canonical closure"
            )
        if self._execution_pool is None or self._experiment_bindings is None:
            raise CanonicalResearchOSRuntimeUnsupported(
                "Experimentation execution is not explicitly bound"
            )
        runtime_binding = self._experiment_bindings.resolve(closure)
        if type(runtime_binding) is not ResearchOSExperimentRuntimeBinding:
            raise TypeError(
                "experiment runtime binding resolver returned invalid binding"
            )
        observed_admission = self._experiment_admission_binding_digest(
            lowering,
            runtime_binding,
        )
        if observed_admission != admission_binding_digest:
            raise CanonicalResearchOSRuntimeFailure(
                "Experiment runtime binding drifted after admission"
            )

        group = self._execution_pool.open_experiment_group(
            f"research-os-experiment:{canonical_digest({'machine_id': machine_id})}",
            tenant_id=execution_tenant_id,
            resource_id=(
                "research-os-experiment:"
                f"{closure.research_plan.experiment.experiment_id}"
            ),
            resource_demand=(
                ResourceCompetitionDemand(
                    storage_targets=(
                        StorageCompetitionDemand(self._state_root),
                    ),
                )
                if self._execution_pool.resource_competition_enabled
                else None
            ),
            deadline=deadline,
        )
        adapter = runtime_binding.adapter
        if scientific_inputs:
            if not isinstance(
                adapter,
                ResearchOSScientificInputBoundStudyExecutionPort,
            ):
                raise CanonicalResearchOSRuntimeUnsupported(
                    "Experiment received upstream scientific inputs but its "
                    "Study execution adapter cannot bind them"
                )
            adapter = adapter.bind_scientific_inputs(scientific_inputs)

        completed = False
        try:
            report = ExperimentProgramBinding(
                closure.experiment_program,
                adapter,
                runtime_binding.aggregation,
                execution_binding_digest=runtime_binding.runtime_binding_digest,
                execution_id=execution_id,
                task_group=group,
                frontier_capacity=self._execution_pool.experiment_frontier_capacity,
            ).execute(
                journal=self._machine_journal,
                machine_id=machine_id,
            )
            if (
                report.protocol_digest
                != closure.experiment_program.plan.protocol.protocol_digest
                or report.binding_digest
                != closure.experiment_program.plan.binding_digest
                or report.plan_digest
                != closure.experiment_program.plan.plan_digest
            ):
                raise CanonicalResearchOSRuntimeFailure(
                    "Experiment report identity drifted from admitted closure"
                )
            report_ref = self._publish_experiment_report(
                lowering,
                runtime_binding,
                report,
                execution_cut_id=execution_cut_id,
            )
            completed = True
            return report_ref if lowering.source.node.outputs else None
        finally:
            self._execution_pool.close_experiment_group(
                group,
                cancel_pending=not completed,
                deadline=deadline,
            )


    def _require_operation_dispatcher(self) -> OperationDispatchPort:
        dispatcher = self._operation_dispatcher
        if dispatcher is None:
            raise CanonicalResearchOSRuntimeUnsupported(
                "Method execution requires the managed durable Operation authority"
            )
        return dispatcher

    def _execute_method(
        self,
        context: ExecutionContext,
        machine_id: str,
        node: CompiledResearchOSGraphNode,
        lowering: LoweredResearchOSGraphNode,
        payload: JsonValue,
        runtime_binding_digest: str,
    ) -> JsonValue:
        program = lowering.method_programs[0].program
        inventory = self._method_inventory_for(node)
        binding_plan = self._method_binding_plan_for(
            program,
            inventory,
        )
        binding_plan.require_complete()
        runtime = bind_standard_method_runtime(
            program,
            MethodRuntimeContext(
                context,
                capabilities=inventory.capabilities,
                agent_loop=inventory.agent_loop,
                schemas=inventory.schemas,
                child_machines=inventory.child_machines,
                dispatcher=self._require_operation_dispatcher(),
                observation=self._method_observation,
                binding_plan_digest=binding_plan.digest,
                runtime_binding_digest=runtime_binding_digest,
            ),
            state_root=self._state_root / "method-state",
            machine_id=machine_id,
        )
        result = execute_bound_method_program(
            program,
            runtime=runtime,
            input_value=payload,
        )
        if result.status is not MethodRunStatus.SUCCEEDED:
            raise CanonicalResearchOSRuntimeFailure(
                "MethodProgram did not reach SUCCEEDED: "
                f"status={result.status.value} "
                f"failure_code={result.failure_code!r} "
                f"failure={result.failure!r}",
                failure_id=result.failure_id,
            )
        return result.value

    def _execute_program(
        self,
        context: ExecutionContext,
        machine_id: str,
        lowering: LoweredResearchOSGraphNode,
        payload: JsonValue,
        runtime_binding_digest: str,
    ) -> JsonValue:
        lowered = lowering.machine_programs[0]
        host = ResearchProgramHost(
            host_id=(
                "research-os:"
                f"{lowering.target.value}:{lowered.definition_id}"
            ),
            program=lowered.program,
            operations=lowered.operations,
            journal=self._machine_journal,
            max_steps=self._max_steps,
            dependency_identity={
                "runtime_binding_digest": runtime_binding_digest,
                "execution_cut_id": context.run_id,
                "graph_node_id": lowering.source.graph_node_id,
            },
        )
        result = host.execute(
            machine_id=machine_id,
            instance_identity={
                "execution_cut_id": context.run_id,
                "graph_node_id": lowering.source.graph_node_id,
                "semantic_digest": lowering.source.semantic_digest,
                "lowering_digest": lowering.lowering_digest,
                "runtime_binding_digest": runtime_binding_digest,
            },
            binding=None,
            initial_data={},
            payload=payload,
            command_id_prefix=machine_id,
        )
        if result.status is not MachineStatus.COMPLETED:
            raise CanonicalResearchOSRuntimeFailure(
                "ResearchProgram did not reach COMPLETED: "
                f"status={result.status.value}"
            )
        return result.previous_value

    def checkpoint_node(
        self,
        node: CompiledResearchOSGraphNode,
        lowering: LoweredResearchOSGraphNode,
        *,
        execution_cut_id: str,
        attempt_id: str,
    ) -> ResearchOSNodeCheckpointProof:
        if type(node) is not CompiledResearchOSGraphNode:
            raise TypeError("canonical checkpoint requires compiled graph node")
        if type(lowering) is not LoweredResearchOSGraphNode:
            raise TypeError("canonical checkpoint requires lowered graph node")
        if lowering.source != node:
            raise ValueError("canonical checkpoint node/lowering identity drifted")
        require_sha256(execution_cut_id, "canonical checkpoint execution_cut_id")
        execution_attempt_id = self._execution_attempt_id(
            execution_cut_id,
            node.graph_node_id,
            attempt_id,
        )
        machine_id = self._machine_id(
            execution_attempt_id,
            node.graph_node_id,
            lowering.lowering_digest,
        )
        journal = (
            self._method_journal
            if lowering.target is ResearchOSLoweringTarget.METHOD_MACHINE
            else self._machine_journal
        )
        head = journal.latest(machine_id)
        if head is None:
            raise ResearchOSCheckpointIndeterminate(
                "lower Machine has no accepted journal head"
            )
        expected_program_digest = self._lower_program_digest(lowering)
        if head.program_digest != expected_program_digest:
            raise CanonicalResearchOSRuntimeFailure(
                "lower Machine journal program identity drifted during checkpoint"
            )
        if head.accepted_status not in {
            MachineStatus.COMPLETED,
            MachineStatus.FAILED,
            MachineStatus.WAITING,
            MachineStatus.INTERRUPTED,
        }:
            raise ResearchOSCheckpointIndeterminate(
                "lower Machine head is not at a checkpoint-safe status: "
                f"{head.accepted_status.value}"
            )
        cut = MachineCut.from_commit(head)
        return ResearchOSNodeCheckpointProof(
            execution_cut_id,
            node.graph_node_id,
            node.semantic_digest,
            lowering.lowering_digest,
            "machine-journal",
            cut,
            (head.commit_id,),
        )

    def reconcile_node(
        self,
        node: CompiledResearchOSGraphNode,
        lowering: LoweredResearchOSGraphNode,
        *,
        execution_cut_id: str,
        attempt_id: str,
    ) -> ResearchOSNodeReconciliationProof:
        if type(node) is not CompiledResearchOSGraphNode:
            raise TypeError("canonical reconciliation requires compiled graph node")
        if type(lowering) is not LoweredResearchOSGraphNode:
            raise TypeError("canonical reconciliation requires lowered graph node")
        if lowering.source != node:
            raise ValueError("canonical reconciliation node/lowering identity drifted")
        require_sha256(execution_cut_id, "canonical reconciliation execution_cut_id")
        if type(attempt_id) is not str or not attempt_id.strip():
            raise ValueError("canonical reconciliation attempt_id is required")

        execution_attempt_id = self._execution_attempt_id(
            execution_cut_id,
            node.graph_node_id,
            attempt_id,
        )
        machine_id = self._machine_id(
            execution_attempt_id,
            node.graph_node_id,
            lowering.lowering_digest,
        )
        journal = (
            self._method_journal
            if lowering.target is ResearchOSLoweringTarget.METHOD_MACHINE
            else self._machine_journal
        )
        head = journal.latest(machine_id)
        expected_program_digest = self._lower_program_digest(lowering)
        if head is not None:
            if head.program_digest != expected_program_digest:
                raise CanonicalResearchOSRuntimeFailure(
                    "lower Machine journal program identity drifted during reconciliation"
                )
            if head.accepted_status is MachineStatus.COMPLETED:
                result = self._recovered_result(
                    node,
                    lowering,
                    head.state,
                    execution_cut_id=execution_cut_id,
                )
                return ResearchOSNodeReconciliationProof(
                    execution_cut_id,
                    node.graph_node_id,
                    node.semantic_digest,
                    lowering.lowering_digest,
                    attempt_id,
                    ResearchGraphReconciliationDisposition.SUCCEEDED,
                    "machine-journal",
                    (head.commit_id,),
                    result=result,
                )
            if head.accepted_status is MachineStatus.FAILED:
                return ResearchOSNodeReconciliationProof(
                    execution_cut_id,
                    node.graph_node_id,
                    node.semantic_digest,
                    lowering.lowering_digest,
                    attempt_id,
                    ResearchGraphReconciliationDisposition.FAILED,
                    "machine-journal",
                    (head.commit_id,),
                    failure_type="LowerMachineFailed",
                    failure_message=(
                        "lower Machine committed FAILED at "
                        f"revision={head.revision} commit={head.commit_id}"
                    ),
                )

        if lowering.target is ResearchOSLoweringTarget.EXPERIMENTATION:
            closure = lowering.experiment_closure
            if closure is None or self._experiment_bindings is None:
                raise ResearchOSReconciliationIndeterminate(
                    "Experiment reconciliation has no canonical closure/runtime binding"
                )
            binding = self._experiment_bindings.resolve(closure)
            if type(binding) is not ResearchOSExperimentRuntimeBinding:
                raise TypeError(
                    "experiment reconciliation resolver returned invalid binding"
                )
            binding.validate_closure(closure)
            proof = binding.reconciliation.reconcile(
                closure,
                machine_id=machine_id,
                execution_cut_id=execution_cut_id,
                graph_node_id=node.graph_node_id,
                semantic_digest=node.semantic_digest,
                lowering_digest=lowering.lowering_digest,
                attempt_id=attempt_id,
            )
            if type(proof) is not ResearchOSNodeReconciliationProof:
                raise TypeError(
                    "experiment reconciliation authority returned invalid proof"
                )
            proof.validate(
                node,
                lowering,
                execution_cut_id=execution_cut_id,
                attempt_id=attempt_id,
            )
            return proof

        raise ResearchOSReconciliationIndeterminate(
            "lower Machine has no terminal commit proving a safe graph disposition"
        )

    def _lower_program_digest(
        self,
        lowering: LoweredResearchOSGraphNode,
    ) -> str:
        if lowering.target is ResearchOSLoweringTarget.METHOD_MACHINE:
            return lowering.method_programs[0].program.program_digest
        if lowering.target is ResearchOSLoweringTarget.EXPERIMENTATION:
            closure = lowering.experiment_closure
            if closure is None:
                raise CanonicalResearchOSRuntimeUnsupported(
                    "Experiment reconciliation has no closure"
                )
            return closure.experiment_program.program.program_digest
        if lowering.target in self._MACHINE_TARGETS:
            return lowering.machine_programs[0].program.program_digest
        raise CanonicalResearchOSRuntimeUnsupported(
            "reconciliation target has no lower Machine program"
        )

    def _recovered_result(
        self,
        node: CompiledResearchOSGraphNode,
        lowering: LoweredResearchOSGraphNode,
        machine_state: JsonObject,
        *,
        execution_cut_id: str,
    ) -> JsonValue:
        if lowering.target is ResearchOSLoweringTarget.METHOD_MACHINE:
            method_state = machine_state.get("method")
            if not isinstance(method_state, Mapping):
                raise CanonicalResearchOSRuntimeFailure(
                    "completed Method Machine lost canonical method state"
                )
            return method_state.get("previous_value")

        program_state = machine_state.get("_program")
        if not isinstance(program_state, Mapping):
            raise CanonicalResearchOSRuntimeFailure(
                "completed ResearchProgram Machine lost canonical program state"
            )
        if lowering.target is ResearchOSLoweringTarget.EXPERIMENTATION:
            closure = lowering.experiment_closure
            if closure is None or self._experiment_bindings is None:
                raise CanonicalResearchOSRuntimeFailure(
                    "completed Experiment Machine lost runtime closure"
                )
            data = program_state.get("data")
            report = experiment_report_from_data(
                closure.experiment_program,
                data,
            )
            binding = self._experiment_bindings.resolve(closure)
            if type(binding) is not ResearchOSExperimentRuntimeBinding:
                raise TypeError(
                    "experiment recovery resolver returned invalid binding"
                )
            binding.validate_closure(closure)
            report_ref = self._publish_experiment_report(
                lowering,
                binding,
                report,
                execution_cut_id=execution_cut_id,
            )
            return report_ref if node.node.outputs else None
        return program_state.get("previous_value")


    @staticmethod
    def _execution_attempt_id(
        execution_cut_id: str,
        graph_node_id: str,
        attempt_id: str,
    ) -> str:
        require_sha256(execution_cut_id, "Research OS execution cut identity")
        if type(graph_node_id) is not str or not graph_node_id.strip():
            raise ValueError("Research OS graph_node_id is required")
        if type(attempt_id) is not str or not attempt_id.strip():
            raise ValueError("Research OS attempt_id is required")
        return canonical_digest(
            {
                "schema": "noetrium.research-node-attempt.v1",
                "execution_cut_id": execution_cut_id,
                "graph_node_id": graph_node_id,
                "attempt_id": attempt_id,
            }
        )

    @staticmethod
    def _machine_id(
        execution_attempt_id: str,
        graph_node_id: str,
        lowering_digest: str,
    ) -> str:
        """Return the stable lower-Machine identity for one durable graph attempt.

        lowering_digest is validated by admission/program identity, but is deliberately
        excluded from Machine identity. Reconciliation must address the same durable
        attempt after a control-plane/code restart even when a new lowering implementation
        would produce a different digest.
        """
        require_sha256(
            execution_attempt_id,
            "Research OS execution attempt identity",
        )
        if type(graph_node_id) is not str or not graph_node_id.strip():
            raise ValueError("Research OS graph_node_id is required")
        require_sha256(lowering_digest, "Research OS lowering digest")
        identity = canonical_digest(
            {
                "schema": "noetrium.research-os-machine-identity.v2",
                "execution_attempt_id": execution_attempt_id,
                "graph_node_id": graph_node_id,
            }
        )
        return f"research-os:{identity}"


__all__ = [
    "CanonicalResearchOSNodeRuntime",
    "CanonicalResearchOSRuntimeFailure",
    "CanonicalResearchOSRuntimeUnsupported",
]
