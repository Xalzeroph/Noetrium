from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.unit_host import BoundExecutableUnit

from collections.abc import Callable, Mapping
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort

from noetrium_platform.capabilities.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import (
    unit_execution_failure,
    MachineJournalPort,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_digest,
)
from noetrium_platform.research.execution.machines.api import (
    CapabilityMediationDenied,
    CapabilityMediatorRegistryPort,
    CAPABILITY_PROGRAM_TRAIT,
    CapabilityProgramBinding,
    default_capability_program_binding,
    CapabilityRuntimeBinding,
    compose_runtime_program,
    capability_mediator_binding_digest,
    capability_runtime_module,
    capability_runtime_operations,
)


class CapabilityInvocationPipeline:
    """RuntimeMachine-backed capability mediation around provider mechanics."""

    def __init__(
        self,
        *,
        journal: MachineJournalPort,
        snapshot_store: MachineSnapshotStorePort | None = None,
        program: NoetriumUnit,
        mediators: CapabilityMediatorRegistryPort,
    ) -> None:
        if not isinstance(journal, MachineJournalPort):
            raise TypeError("capability pipeline requires MachineJournalPort")
        if type(program) is not NoetriumUnit or not program.has_trait(CAPABILITY_PROGRAM_TRAIT):
            raise TypeError("capability pipeline requires capability-program NoetriumUnit")
        if not isinstance(mediators, CapabilityMediatorRegistryPort):
            raise TypeError("capability pipeline requires mediator registry")
        self._program = program
        self._mediators = mediators
        self._program_binding_digest = capability_mediator_binding_digest(
            program,
            mediators,
        )
        module = capability_runtime_module(program)
        runtime_program = compose_runtime_program(
            program_id=f"runtime.capability:{program.unit_id}",
            version=str(program.parameters["version"]),
            state_schema="runtime.capability.invocation.state.v1",
            entry_module=module.unit_id,
            modules=(module,),
        )
        self._host = BoundExecutableUnit(
            host_id="runtime.capability.invocation",
            unit=runtime_program,
            operations=capability_runtime_operations(),
            journal=journal,
            snapshot_store=snapshot_store,
            max_steps=None,
            dependency_identity={
                "capability_program_digest": program.semantic_digest,
                "capability_program_binding_digest": (
                    self._program_binding_digest
                ),
                "mediator_registry_identity_digest": (
                    mediators.identity_digest
                ),
            },
        )

    def invoke(
        self,
        *,
        invocation_id: str,
        descriptor: CapabilityDescriptor,
        request: CapabilityRequest,
        control: ExecutionControlPort,
        execute: Callable[[CapabilityRequest, ExecutionControlPort], CapabilityResult],
    ) -> CapabilityResult:
        if type(invocation_id) is not str or not invocation_id.strip():
            raise ValueError("capability invocation_id is required")
        if not isinstance(descriptor, CapabilityDescriptor):
            raise TypeError("capability pipeline requires CapabilityDescriptor")
        if not isinstance(request, CapabilityRequest):
            raise TypeError("capability pipeline requires CapabilityRequest")
        if not isinstance(control, ExecutionControlPort):
            raise TypeError("capability pipeline requires ExecutionControlPort")
        if descriptor.capability_id != request.capability_id:
            raise ValueError("capability descriptor/request identity mismatch")
        if not callable(execute):
            raise TypeError("capability provider execute must be callable")

        binding = CapabilityRuntimeBinding(
            self._program,
            self._mediators,
            descriptor,
            request,
            control,
            execute,
        )
        binding_digest = binding.binding_digest
        invocation_digest = canonical_digest({
            "invocation_id": invocation_id,
            "run_id": request.context.run_id,
            "capability_id": request.capability_id,
            "program_digest": self._program.semantic_digest,
            "program_binding_digest": self._program_binding_digest,
            "binding_digest": binding_digest,
        })
        base_machine_id = (
            f"runtime-capability:{request.context.run_id}:"
            f"{invocation_digest[:24]}"
        )
        control.checkpoint()
        execution = self._host.execute(
            machine_id=self._host.terminal_replay_machine_id(base_machine_id),
            instance_identity={
                "invocation_id": invocation_id,
                "invocation_digest": invocation_digest,
                "run_id": request.context.run_id,
                "capability_id": request.capability_id,
                "descriptor_digest": descriptor.digest(),
                "program_digest": self._program.semantic_digest,
                "program_binding_digest": self._program_binding_digest,
                "binding_digest": binding_digest,
            },
            binding=binding,
            initial_data={
                "invocation_id": invocation_id,
                "invocation_digest": invocation_digest,
                "capability_id": request.capability_id,
                "descriptor_digest": descriptor.digest(),
                "program_digest": self._program.semantic_digest,
                "program_binding_digest": self._program_binding_digest,
                "binding_digest": binding_digest,
            },
            payload={"source": "capability-invocation"},
            command_id_prefix=f"runtime-capability:{invocation_digest[:24]}",
        )
        control.checkpoint()
        if execution.status is MachineStatus.FAILED:
            rule_id = execution.data.get("mediation_denied_rule")
            reason = execution.data.get("mediation_denied_reason")
            stage = execution.data.get("mediation_denied_stage")
            completed = execution.data.get("execution_completed", False)
            if (
                type(rule_id) is str
                and type(reason) is str
                and type(stage) is str
                and isinstance(completed, bool)
            ):
                from noetrium_platform.research.execution.machines.api import (
                    CapabilityMediationStage,
                )
                raise CapabilityMediationDenied(
                    rule_id=rule_id,
                    reason_code=reason,
                    stage=CapabilityMediationStage(stage),
                    execution_completed=completed,
                )
            raise unit_execution_failure(
                execution.semantic_state,
                surface="capability RuntimeProgram",
            )
        if execution.status is not MachineStatus.COMPLETED:
            raise RuntimeError(
                "capability RuntimeProgram stopped before completion: "
                f"{execution.status.value}"
            )
        if binding.result is None:
            raise RuntimeError(
                "capability RuntimeProgram completed without provider result"
            )
        if binding.result.capability_id != descriptor.capability_id:
            raise ValueError("capability provider returned mismatched capability_id")
        return binding.result


class CapabilityInvocationPipelineFactory:
    def __init__(
        self,
        journal: MachineJournalPort,
        *,
        snapshot_store: MachineSnapshotStorePort | None = None,
    ) -> None:
        if not isinstance(journal, MachineJournalPort):
            raise TypeError("capability pipeline factory requires MachineJournalPort")
        self._journal = journal
        self._snapshot_store = snapshot_store

    def create(
        self,
        program_binding: CapabilityProgramBinding | None = None,
    ) -> CapabilityInvocationPipeline:
        selected = (
            default_capability_program_binding()
            if program_binding is None
            else program_binding
        )
        if not isinstance(selected, CapabilityProgramBinding):
            raise TypeError(
                "capability pipeline requires capability-program NoetriumUnitBinding"
            )
        return CapabilityInvocationPipeline(
            journal=self._journal,
            snapshot_store=self._snapshot_store,
            program=selected.program,
            mediators=selected.mediators,
        )


__all__ = [
    "CapabilityInvocationPipeline",
    "CapabilityInvocationPipelineFactory",
]
