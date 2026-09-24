from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
from pathlib import Path

from noetrium_platform.composition.method_runtime import (
    bind_standard_method_runtime,
    standard_method_runtime_binder,
)
from noetrium_platform.foundation.kernel.concurrency.api import Deadline
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
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
from noetrium_platform.research.experimentation.lifecycle.api import (
    RunArtifactKind,
    RunArtifactSealedError,
    RunArtifactSnapshotReceipt,
)
from noetrium_platform.product.research_os import ResearchValueKind
from noetrium_platform.research.execution.workflow.api import (
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.runtime import (
    UniversalMethodMachine,
)

from .research_os_checkpoint import (
    ResearchOSCheckpointIndeterminate,
    ResearchOSNodeCheckpointProof,
)
from .research_os_experiment import (
    ResearchOSExperimentRuntimeBinding,
    ResearchOSExperimentRuntimeBindingPort,
)
from .research_os_execution import (
    ResearchOSNodeAdmission,
    ResearchOSNodeRuntimePort,
)
from .research_os_graph import CompiledResearchOSGraphNode
from .research_os_lowering import (
    LoweredResearchOSGraphNode,
    ResearchOSLoweringTarget,
)
from .research_os_reconciliation import (
    ResearchOSNodeReconciliationProof,
    ResearchOSReconciliationIndeterminate,
)


class CanonicalResearchOSRuntimeUnsupported(RuntimeError):
    pass


class CanonicalResearchOSRuntimeFailure(RuntimeError):
    pass


class CanonicalResearchOSNodeRuntime(ResearchOSNodeRuntimePort):
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
        max_steps: int = 10_000,
    ) -> None:
        if not isinstance(state_root, (str, Path)):
            raise TypeError("canonical Research OS runtime state_root is required")
        root = Path(state_root).absolute()
        if root.exists() and not root.is_dir():
            raise ValueError("canonical Research OS runtime state_root must be a directory")
        if type(max_steps) is not int or max_steps < 1:
            raise ValueError("canonical Research OS runtime max_steps must be positive")
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
        root.mkdir(parents=True, exist_ok=True)
        self._state_root = root
        self._execution_pool = execution_pool
        self._experiment_bindings = experiment_bindings
        self._max_steps = max_steps
        self._machine_journal = DirectoryMachineJournal(root / "program-journal")
        self._method_journal = DirectoryMachineJournal(root / "method-state" / "journal")
        self._method_binder_digest = standard_method_runtime_binder().identity_digest

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
            runtime_binding.validate_closure(closure)
            binding_digest = canonical_digest(
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
                    "journal": "directory-machine-journal",
                }
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
            if program.required_capabilities or program.required_runtime_ports:
                raise CanonicalResearchOSRuntimeUnsupported(
                    "canonical pure Method runtime cannot satisfy undeclared external "
                    "runtime dependencies"
                )
            binding_digest = canonical_digest(
                {
                    "runtime": "canonical-research-os-node-runtime",
                    "version": 1,
                    "target": lowering.target.value,
                    "program_digest": program.program_digest,
                    "method_runtime_binder_digest": self._method_binder_digest,
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
                    "operation_digest": lowered.operation.implementation_digest,
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
        node: CompiledResearchOSGraphNode,
        lowering: LoweredResearchOSGraphNode,
        inputs: JsonObject,
        *,
        execution_cut_id: str,
        deadline: Deadline | None,
    ) -> JsonValue:
        if not isinstance(context, ExecutionContext):
            raise TypeError("canonical Research OS runtime requires ExecutionContext")
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
            run_id=execution_cut_id,
            component_id=node.graph_node_id,
        )
        payload: JsonValue = inputs if inputs else None
        machine_id = self._machine_id(
            execution_cut_id,
            node.graph_node_id,
            lowering.lowering_digest,
        )

        if lowering.target is ResearchOSLoweringTarget.EXPERIMENTATION:
            return self._execute_experiment(
                machine_id,
                lowering,
                admission.runtime_binding_digest,
                deadline=deadline,
            )
        if lowering.target is ResearchOSLoweringTarget.METHOD_MACHINE:
            return self._execute_method(
                runtime_context,
                machine_id,
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

    @staticmethod
    def _receipt_json(
        receipt: RunArtifactSnapshotReceipt,
    ) -> JsonObject:
        return {
            "run_id": receipt.run_id,
            "artifact_ref": receipt.artifact_ref,
            "artifact_kind": receipt.artifact_kind.value,
            "generation": receipt.generation,
            "content_sha256": receipt.content_sha256,
            "byte_size": receipt.byte_size,
            "record_count": receipt.record_count,
        }

    @staticmethod
    def _publish_exact_finalized_json(
        artifacts,
        name: str,
        payload: JsonValue,
        *,
        kind: RunArtifactKind,
    ) -> RunArtifactSnapshotReceipt:
        body = canonical_bytes(payload, indent=2) + b"\n"
        expected_sha = hashlib.sha256(body).hexdigest()
        expected_size = len(body)
        try:
            artifacts.publish_text(
                name,
                body.decode("utf-8"),
                kind=kind,
            )
        except RunArtifactSealedError:
            # Exact-identity recovery only: the immutable sealed artifact must
            # already contain precisely the bytes this execution intends to publish.
            receipt = artifacts.finalize(
                name,
                kind=kind,
                record_stream=False,
            )
            verified = artifacts.verify_finalized(receipt)
            if (
                verified.content_sha256 != expected_sha
                or verified.byte_size != expected_size
            ):
                raise CanonicalResearchOSRuntimeFailure(
                    "sealed Experiment artifact content drifted during recovery"
                )
            return verified

        receipt = artifacts.finalize(
            name,
            kind=kind,
            record_stream=False,
        )
        verified = artifacts.verify_finalized(receipt)
        if (
            verified.content_sha256 != expected_sha
            or verified.byte_size != expected_size
        ):
            raise CanonicalResearchOSRuntimeFailure(
                "Experiment artifact finalization identity drifted"
            )
        return verified

    def _publish_experiment_report(
        self,
        lowering: LoweredResearchOSGraphNode,
        runtime_binding: ResearchOSExperimentRuntimeBinding,
        report,
    ) -> JsonObject:
        closure = lowering.experiment_closure
        if closure is None:
            raise CanonicalResearchOSRuntimeUnsupported(
                "Experiment report publication has no canonical closure"
            )
        prefix = f"research-os/experiments/{closure.closure_digest}"
        protocol = self._publish_exact_finalized_json(
            runtime_binding.artifacts,
            f"{prefix}/protocol.json",
            {
                "protocol": asdict(closure.experiment_program.plan.protocol),
                "assignments": tuple(
                    asdict(row)
                    for row in closure.experiment_program.plan.assignments
                ),
            },
            kind=RunArtifactKind.MANIFEST,
        )
        observations = self._publish_exact_finalized_json(
            runtime_binding.artifacts,
            f"{prefix}/observations.json",
            tuple(asdict(row) for row in report.observations),
            kind=RunArtifactKind.METRIC,
        )
        aggregates = self._publish_exact_finalized_json(
            runtime_binding.artifacts,
            f"{prefix}/aggregates.json",
            tuple(asdict(row) for row in report.aggregates),
            kind=RunArtifactKind.METRIC,
        )
        manifest_payload: JsonObject = {
            "schema": "research-os.experiment-report-manifest.v1",
            "closure_digest": closure.closure_digest,
            "research_plan_digest": closure.research_plan.research_plan_digest,
            "experiment_program_digest": (
                closure.experiment_program.program.program_digest
            ),
            "protocol_digest": report.protocol_digest,
            "binding_digest": report.binding_digest,
            "plan_digest": report.plan_digest,
            "observation_count": len(report.observations),
            "aggregate_count": len(report.aggregates),
            "protocol_artifact": self._receipt_json(protocol),
            "observations_artifact": self._receipt_json(observations),
            "aggregates_artifact": self._receipt_json(aggregates),
        }
        manifest = self._publish_exact_finalized_json(
            runtime_binding.artifacts,
            f"{prefix}/report-manifest.json",
            manifest_payload,
            kind=RunArtifactKind.MANIFEST,
        )
        return {
            "schema": "research-os.experiment-report-ref.v1",
            "closure_digest": closure.closure_digest,
            "manifest": self._receipt_json(manifest),
        }

    def _execute_experiment(
        self,
        machine_id: str,
        lowering: LoweredResearchOSGraphNode,
        admission_binding_digest: str,
        *,
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
        runtime_binding.validate_closure(closure)
        observed_admission = canonical_digest(
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
                "journal": "directory-machine-journal",
            }
        )
        if observed_admission != admission_binding_digest:
            raise CanonicalResearchOSRuntimeFailure(
                "Experiment runtime binding drifted after admission"
            )

        group = self._execution_pool.open_experiment_group(
            f"research-os-experiment:{canonical_digest({'machine_id': machine_id})}",
            resource_id=(
                "research-os-experiment:"
                f"{closure.research_plan.experiment.experiment_id}"
            ),
            deadline=deadline,
        )
        completed = False
        try:
            report = ExperimentProgramBinding(
                closure.experiment_program,
                runtime_binding.adapter,
                runtime_binding.aggregation,
                task_group=group,
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
            )
            completed = True
            return report_ref if lowering.source.node.outputs else None
        finally:
            self._execution_pool.close_experiment_group(
                group,
                cancel_pending=not completed,
                deadline=deadline,
            )


    def _execute_method(
        self,
        context: ExecutionContext,
        machine_id: str,
        lowering: LoweredResearchOSGraphNode,
        payload: JsonValue,
        runtime_binding_digest: str,
    ) -> JsonValue:
        program = lowering.method_programs[0].program
        runtime = bind_standard_method_runtime(
            program,
            MethodRuntimeContext(
                context,
                runtime_binding_digest=runtime_binding_digest,
            ),
            state_root=self._state_root / "method-state",
            machine_id=machine_id,
        )
        result = UniversalMethodMachine(
            max_steps=self._max_steps,
        ).run(
            program,
            runtime=runtime,
            input_value=payload,
        )
        if result.status is not MethodRunStatus.SUCCEEDED:
            raise CanonicalResearchOSRuntimeFailure(
                "MethodProgram did not reach SUCCEEDED: "
                f"status={result.status.value} "
                f"failure_code={result.failure_code!r} "
                f"failure={result.failure!r}"
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
            operations=(lowered.operation,),
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
    ) -> ResearchOSNodeCheckpointProof:
        if type(node) is not CompiledResearchOSGraphNode:
            raise TypeError("canonical checkpoint requires compiled graph node")
        if type(lowering) is not LoweredResearchOSGraphNode:
            raise TypeError("canonical checkpoint requires lowered graph node")
        if lowering.source != node:
            raise ValueError("canonical checkpoint node/lowering identity drifted")
        require_sha256(execution_cut_id, "canonical checkpoint execution_cut_id")
        machine_id = self._machine_id(
            execution_cut_id,
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

        machine_id = self._machine_id(
            execution_cut_id,
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
    ) -> JsonValue:
        if lowering.target is ResearchOSLoweringTarget.METHOD_MACHINE:
            method_state = machine_state.get("method")
            if not isinstance(method_state, dict):
                raise CanonicalResearchOSRuntimeFailure(
                    "completed Method Machine lost canonical method state"
                )
            return method_state.get("previous_value")

        program_state = machine_state.get("_program")
        if not isinstance(program_state, dict):
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
            )
            return report_ref if node.node.outputs else None
        return program_state.get("previous_value")


    @staticmethod
    def _machine_id(
        execution_cut_id: str,
        graph_node_id: str,
        lowering_digest: str,
    ) -> str:
        identity = canonical_digest(
            {
                "execution_cut_id": execution_cut_id,
                "graph_node_id": graph_node_id,
                "lowering_digest": lowering_digest,
            }
        )
        return f"research-os:{identity}"


__all__ = [
    "CanonicalResearchOSNodeRuntime",
    "CanonicalResearchOSRuntimeFailure",
    "CanonicalResearchOSRuntimeUnsupported",
]
