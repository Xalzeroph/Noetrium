from __future__ import annotations

from collections.abc import Callable

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityPolicySet,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.foundation.kernel.kernel import (
    MachineJournalPort,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_digest,
)
from noetrium_platform.research.execution.machines import (
    CapabilityMediationDenied,
    CapabilityMediatorRegistryPort,
    CapabilityProgram,
    CapabilityRuntimeBinding,
    ResearchProgramHost,
    RuntimeProgramComposer,
    capability_mediator_binding_digest,
    capability_program_from_policy,
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
        program: CapabilityProgram,
        mediators: CapabilityMediatorRegistryPort,
    ) -> None:
        if not isinstance(journal, MachineJournalPort):
            raise TypeError("capability pipeline requires MachineJournalPort")
        if not isinstance(program, CapabilityProgram):
            raise TypeError("capability pipeline requires CapabilityProgram")
        if not isinstance(mediators, CapabilityMediatorRegistryPort):
            raise TypeError("capability pipeline requires mediator registry")
        self._program = program
        self._mediators = mediators
        self._program_binding_digest = capability_mediator_binding_digest(
            program,
            mediators,
        )
        module = capability_runtime_module(program)
        runtime_program = (
            RuntimeProgramComposer(
                program_id=f"runtime.capability:{program.program_id}",
                version=program.version,
                state_schema="runtime.capability.invocation.state.v1",
                entry_module=module.module_id,
            )
            .module(module)
            .build()
        )
        self._host = ResearchProgramHost(
            host_id="runtime.capability.invocation",
            program=runtime_program,
            operations=capability_runtime_operations(),
            journal=journal,
            snapshot_store=snapshot_store,
            max_steps=16,
            dependency_identity={
                "capability_program_digest": program.program_digest,
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
        execute: Callable[[CapabilityRequest], CapabilityResult],
    ) -> CapabilityResult:
        if type(invocation_id) is not str or not invocation_id.strip():
            raise ValueError("capability invocation_id is required")
        if not isinstance(descriptor, CapabilityDescriptor):
            raise TypeError("capability pipeline requires CapabilityDescriptor")
        if not isinstance(request, CapabilityRequest):
            raise TypeError("capability pipeline requires CapabilityRequest")
        if descriptor.capability_id != request.capability_id:
            raise ValueError("capability descriptor/request identity mismatch")
        if not callable(execute):
            raise TypeError("capability provider execute must be callable")

        binding = CapabilityRuntimeBinding(
            self._program,
            self._mediators,
            descriptor,
            request,
            execute,
        )
        binding_digest = binding.binding_digest
        invocation_digest = canonical_digest({
            "invocation_id": invocation_id,
            "run_id": request.context.run_id,
            "capability_id": request.capability_id,
            "program_digest": self._program.program_digest,
            "program_binding_digest": self._program_binding_digest,
            "binding_digest": binding_digest,
        })
        execution = self._host.execute(
            machine_id=(
                f"runtime-capability:{request.context.run_id}:"
                f"{invocation_digest[:24]}"
            ),
            instance_identity={
                "invocation_id": invocation_id,
                "invocation_digest": invocation_digest,
                "run_id": request.context.run_id,
                "capability_id": request.capability_id,
                "descriptor_digest": descriptor.digest(),
                "program_digest": self._program.program_digest,
                "program_binding_digest": self._program_binding_digest,
                "binding_digest": binding_digest,
            },
            binding=binding,
            initial_data={
                "invocation_id": invocation_id,
                "invocation_digest": invocation_digest,
                "capability_id": request.capability_id,
                "descriptor_digest": descriptor.digest(),
                "program_digest": self._program.program_digest,
                "program_binding_digest": self._program_binding_digest,
                "binding_digest": binding_digest,
            },
            payload={"source": "capability-invocation"},
            command_id_prefix=f"runtime-capability:{invocation_digest[:24]}",
        )
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
                from noetrium_platform.research.execution.machines import (
                    CapabilityMediationStage,
                )
                raise CapabilityMediationDenied(
                    rule_id=rule_id,
                    reason_code=reason,
                    stage=CapabilityMediationStage(stage),
                    execution_completed=completed,
                )
            raise RuntimeError("capability RuntimeProgram entered FAILED state")
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
        program: CapabilityProgram | None = None,
        mediators: CapabilityMediatorRegistryPort | None = None,
    ) -> None:
        if not isinstance(journal, MachineJournalPort):
            raise TypeError("capability pipeline factory requires MachineJournalPort")
        if (program is None) != (mediators is None):
            raise ValueError(
                "custom CapabilityProgram and mediator registry must be supplied together"
            )
        self._journal = journal
        self._snapshot_store = snapshot_store
        self._program = program
        self._mediators = mediators

    def create(
        self,
        policy: CapabilityPolicySet | None = None,
    ) -> CapabilityInvocationPipeline:
        if self._program is not None:
            if policy is not None:
                raise ValueError(
                    "custom CapabilityProgram cannot be combined with CapabilityPolicySet"
                )
            program = self._program
            mediators = self._mediators
            if mediators is None:
                raise RuntimeError("capability mediator registry is missing")
        else:
            program, mediators = capability_program_from_policy(policy)
        return CapabilityInvocationPipeline(
            journal=self._journal,
            snapshot_store=self._snapshot_store,
            program=program,
            mediators=mediators,
        )


__all__ = [
    "CapabilityInvocationPipeline",
    "CapabilityInvocationPipelineFactory",
]
