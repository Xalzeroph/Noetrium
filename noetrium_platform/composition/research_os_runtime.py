from __future__ import annotations

from dataclasses import replace
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
    MachineStatus,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.research.execution.machines import ResearchProgramHost
from noetrium_platform.research.experimentation.api import ExperimentProgramBinding
from noetrium_platform.research.execution.workflow.api import (
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.runtime import (
    UniversalMethodMachine,
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
        if type(state_root) not in {str, Path}:
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
            if node.node.outputs:
                raise CanonicalResearchOSRuntimeUnsupported(
                    "Experimentation outputs require an explicit report projection contract"
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
            completed = True
            return None
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
