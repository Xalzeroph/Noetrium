from __future__ import annotations

from noetrium_platform.research.experimentation.lifecycle.api import ExperimentModelRoleSpec, ExperimentParticipantSpec, ExperimentSpec
from noetrium_platform.capabilities.participant.core.api.contracts import (
    ParticipantImplementationIdentity, ParticipantRuntimeBinding, ParticipantSessionRuntimeIdentity,
)
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantRuntimeHandle
from noetrium_platform.research.execution.workflow.api import ExecutionTrialProtocolKind, TrialCycleExecution


def _digest_seed(value: str) -> str:
    import hashlib
    return value if len(value) == 64 and all(ch in "0123456789abcdef" for ch in value) else hashlib.sha256(value.encode()).hexdigest()


def model_role_for_test(
    role: str = "policy",
    *,
    requirement_id: str = "model.test",
    provider_id: str = "model.test-provider",
    model_identity_seed: str = "model.test-identity",
    model_stack_seed: str = "model.test-stack",
    binding_seed: str = "model.test-binding",
    prompt_generation_id: str | None = "prompt",
) -> ExperimentModelRoleSpec:
    return ExperimentModelRoleSpec(
        role=role,
        requirement_id=requirement_id,
        provider_id=provider_id,
        deployment_id=f"deployment-{role}",
        deployment_generation=_digest_seed(f"deployment-generation:{role}"),
        model_identity_digest=_digest_seed(model_identity_seed),
        model_stack_digest=_digest_seed(model_stack_seed),
        binding_digest=_digest_seed(binding_seed),
        prompt_generation_id=prompt_generation_id,
    )


class _TestParticipantRuntimeEndpoint:
    """Test-only adapter for legacy-shaped doubles; production resolvers never use it."""

    def __init__(self, binding: ParticipantRuntimeBinding, endpoint: object) -> None:
        self.implementation_identity = binding.implementation
        self.runtime_identity = binding.runtime
        self._endpoint = endpoint

    @property
    def identity(self):
        return self._endpoint.identity

    def open_session(self, *, session_id: str, services: object):
        return self._endpoint.open_session(session_id=session_id, services=services)


class FakeParticipantResolver:
    """Test double for the execution-side resolver port; production catalogs are tested separately."""

    def __init__(self) -> None:
        self._factories = {}

    def register(self, kind: str, participant_id: str, factory) -> None:
        key = (kind, participant_id)
        if key in self._factories:
            raise ValueError(f"duplicate test participant: {kind}:{participant_id}")
        self._factories[key] = factory

    def resolve(self, binding: ParticipantRuntimeBinding) -> ParticipantRuntimeHandle:
        key = (binding.implementation.kind, binding.implementation.participant_id)
        try:
            factory = self._factories[key]
        except KeyError as exc:
            raise KeyError(f"unknown test participant: {key}") from exc
        endpoint = factory()
        if getattr(endpoint, "runtime_identity", None) == binding.runtime:
            return ParticipantRuntimeHandle(binding, endpoint)
        return ParticipantRuntimeHandle(binding, _TestParticipantRuntimeEndpoint(binding, endpoint))

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted({kind for kind, _ in self._factories}))


class CompositeParticipantResolver:
    def __init__(self, *resolvers) -> None:
        self._resolvers = tuple(row for row in resolvers if row is not None)

    def resolve(self, binding: ParticipantRuntimeBinding) -> ParticipantRuntimeHandle:
        errors=[]
        for resolver in self._resolvers:
            try:
                return resolver.resolve(binding)
            except KeyError as exc:
                errors.append(exc)
        raise KeyError(f"no resolver owns {binding.implementation.kind}:{binding.implementation.participant_id}")


def runtime_identity_for_test(kind: str, runtime_id: str | None = None) -> ParticipantSessionRuntimeIdentity:
    import hashlib
    rid = runtime_id or f"test.{kind}.session_runtime"
    artifact = hashlib.sha256(f"{rid}:1:abi1".encode()).hexdigest()
    return ParticipantSessionRuntimeIdentity(rid, "1", "abi1", artifact)


def participant(
    kind: str,
    role: str,
    plugin_id: str,
    *,
    implementation_version: str = "1",
    abi_version: str = "1",
    schema_version: str = "1",
    configuration_digest: str = "",
    artifact_digest: str | None = "",
    runtime_id: str | None = None,
    depends_on_roles: tuple[str, ...] = (),
) -> ExperimentParticipantSpec:
    import hashlib
    artifact_seed = artifact_digest
    resolved_artifact = (
        artifact_seed
        if artifact_seed is None or (len(artifact_seed) == 64 and all(ch in "0123456789abcdef" for ch in artifact_seed))
        else hashlib.sha256(artifact_seed.encode()).hexdigest()
    )
    configuration_seed = configuration_digest or f"{kind}:{plugin_id}:configuration"
    resolved_configuration = (
        configuration_seed
        if len(configuration_seed) == 64 and all(ch in "0123456789abcdef" for ch in configuration_seed)
        else hashlib.sha256(configuration_seed.encode()).hexdigest()
    )
    return ExperimentParticipantSpec(
        role=role,
        implementation=ParticipantImplementationIdentity(
            kind, plugin_id, implementation_version or "1", abi_version or "1", schema_version or "1", resolved_artifact
        ),
        runtime=runtime_identity_for_test(kind, runtime_id),
        configuration_digest=resolved_configuration,
        depends_on_roles=depends_on_roles,
    )


def context_action_spec(
    study_id: str = "s",
    method_id: str = "m",
    environment_id: str = "e",
    *,
    experiment_id: str = "default-experiment",
    project_id: str = "default-project",
    model_roles: tuple[ExperimentModelRoleSpec, ...] | None = None,
    workload_digest: str = "b" * 64,
    seed_digest: str = "c" * 64,
    repetitions: int = 1,
    method_implementation_version: str = "",
    method_abi_version: str = "",
    method_schema_version: str = "",
    method_configuration_digest: str = "",
    method_artifact_digest: str | None = None,
    environment_implementation_version: str = "",
    environment_abi_version: str = "",
    environment_schema_version: str = "",
    environment_configuration_digest: str = "",
    environment_artifact_digest: str | None = None,
    scientific_workflow_id: str = "context_action.v5",
    scientific_workflow_configuration_digest: str = "",
) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=experiment_id,
        study_id=study_id,
        project_id=project_id,
        participants=(
            participant(
                "method", "method", method_id,
                implementation_version=method_implementation_version,
                abi_version=method_abi_version,
                schema_version=method_schema_version,
                configuration_digest=method_configuration_digest, artifact_digest=method_artifact_digest,
            ),
            participant(
                "environment", "environment", environment_id,
                implementation_version=environment_implementation_version,
                abi_version=environment_abi_version,
                schema_version=environment_schema_version,
                configuration_digest=environment_configuration_digest, artifact_digest=environment_artifact_digest,
            ),
        ),
        model_roles=(model_role_for_test(),) if model_roles is None else model_roles,
        workload_digest=_digest_seed(workload_digest),
        seed_digest=_digest_seed(seed_digest),
        repetitions=repetitions,
        trial_protocol_id=scientific_workflow_id,
        trial_protocol_configuration_digest=(
            __import__(
                "noetrium_platform.composition.workflows.context_action",
                fromlist=["CONTEXT_ACTION_TRIAL_CONFIGURATION_DIGEST"],
            ).CONTEXT_ACTION_TRIAL_CONFIGURATION_DIGEST
            if not scientific_workflow_configuration_digest
            else _digest_seed(scientific_workflow_configuration_digest)
        ),
    )


def study_spec(
    study_id: str,
    participants: tuple[ExperimentParticipantSpec, ...],
    *,
    experiment_id: str = "default-experiment",
    project_id: str = "default-project",
    model_roles: tuple[ExperimentModelRoleSpec, ...] | None = None,
    workload_digest: str = "b" * 64,
    seed_digest: str = "c" * 64,
    repetitions: int = 1,
    scientific_workflow_id: str,
    scientific_workflow_configuration_digest: str = "",
) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=experiment_id,
        study_id=study_id,
        project_id=project_id,
        participants=participants,
        model_roles=(model_role_for_test(),) if model_roles is None else model_roles,
        workload_digest=_digest_seed(workload_digest),
        seed_digest=_digest_seed(seed_digest),
        repetitions=repetitions,
        trial_protocol_id=scientific_workflow_id,
        trial_protocol_configuration_digest=_digest_seed(scientific_workflow_configuration_digest),
    )



def participant_component(spec):
    from noetrium_platform.foundation.kernel.kernel import ComponentIdentity
    binding = spec.runtime_binding()
    implementation = binding.implementation
    return ComponentIdentity(
        f"participant.{binding.role}",
        binding.digest(),
        implementation.implementation_version,
        implementation.schema_version,
        binding.runtime.digest(),
    )

def environment_effect_intent(request, provider_component, *, operation_id: str, recovery_handle=None):
    from noetrium_platform.infrastructure.reliability.effect.api import EffectIntent
    from noetrium_platform.capabilities.environment.api import action_request_digest

    return EffectIntent.build(
        request_id=request.action_id,
        request_digest=action_request_digest(request),
        operation_id=operation_id,
        provider_component=provider_component,
        context=request.context,
        source_generation=request.context.generation("environment"),
        recovery_handle=recovery_handle,
        intent_namespace="environment-effect",
    )

class NoOpTrialProtocol:
    protocol_kind = ExecutionTrialProtocolKind.RUNTIME_PROGRAM
    protocol_id = "test-noop.v1"
    surface_id = "empty.operations.v1"
    configuration_digest = "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"

    def run(self, operations, context, *, task, input_kind, input_payload):
        del operations, input_kind
        return TrialCycleExecution(str(task), input_payload, context, ())


class EmptyWorkflowSurfaceFactory:
    surface_id = "empty.operations.v1"

    @staticmethod
    def bind(context):
        del context
        return object()


from dataclasses import dataclass as _dataclass


@_dataclass(frozen=True, slots=True)
class ExperimentRuntimeComponentsForTest:
    trial_protocol_identity: object
    cycle_runtime: object
    run_runtime: object


class ExperimentRuntimeForTest:
    def __init__(
        self,
        trial_protocol_identity,
        cycle_runtime,
        run_runtime,
        *,
        run_identity_provider,
        cycle_identity_provider,
    ) -> None:
        self.trial_protocol_identity = trial_protocol_identity
        self.cycle_runtime = cycle_runtime
        self.run_runtime = run_runtime
        self.run_identity_provider = run_identity_provider
        self.cycle_identity_provider = cycle_identity_provider

    def open_run(
        self,
        spec,
        *,
        run_identity=None,
    ):
        from noetrium_platform.research.experimentation.lifecycle.experiment.api.trial_protocol import (
            verify_trial_protocol_identity,
        )

        verify_trial_protocol_identity(spec, self.trial_protocol_identity)
        identity = run_identity or self.run_identity_provider.allocate()
        return self.run_runtime.open(
            spec,
            identity,
        )

    def execute_cycle(
        self,
        spec,
        *,
        task,
        input_kind="input",
        input_payload=None,
        cycle_identity=None,
    ):
        from noetrium_platform.research.experimentation.lifecycle.experiment.api.trial_protocol import (
            verify_trial_protocol_identity,
        )

        verify_trial_protocol_identity(spec, self.trial_protocol_identity)
        identity = cycle_identity or self.cycle_identity_provider.allocate()
        return self.cycle_runtime.run(
            spec,
            identity,
            task=task,
            input_kind=input_kind,
            input_payload=input_payload,
        )


class ExperimentWorkflowSurfaceRegistryForTest:
    def __init__(self, factories) -> None:
        self._factories = {factory.surface_id: factory for factory in factories}
        if len(self._factories) != len(factories):
            raise ValueError("duplicate workflow surface_id")

    def bind(self, surface_id: str, context):
        try:
            factory = self._factories[surface_id]
        except KeyError as exc:
            raise LookupError(
                f"no workflow surface factory for surface_id={surface_id!r}"
            ) from exc
        return factory.bind(context)

    def reuse_scope(self, surface_id: str):
        from noetrium_platform.research.execution.workflow.api import (
            workflow_surface_reuse_scope,
        )
        try:
            factory = self._factories[surface_id]
        except KeyError as exc:
            raise LookupError(
                f"no workflow surface factory for surface_id={surface_id!r}"
            ) from exc
        return workflow_surface_reuse_scope(factory)


class ExperimentTrialCycleExecutorForTest:
    def __init__(
        self,
        dispatcher,
        trial_protocol,
        *,
        effect_dispatcher=None,
        effect_intents=None,
        workflow_surface_factories=(),
        machine_journal=None,
        machine_snapshot_store=None,
    ) -> None:
        from noetrium_platform.research.execution.workflow.api import (
            require_execution_trial_protocol,
        )

        self.dispatcher = dispatcher
        self.effect_dispatcher = (
            dispatcher if effect_dispatcher is None else effect_dispatcher
        )
        self.trial_protocol = require_execution_trial_protocol(trial_protocol)
        self.effect_intents = effect_intents
        self._surface_registry = ExperimentWorkflowSurfaceRegistryForTest(
            workflow_surface_factories
        )
        self._machine_journal = machine_journal
        self._machine_snapshot_store = machine_snapshot_store
        self._run_surface_key = None
        self._run_surface = None

    def _surface_for(self, *, surface_id, run_id, surface_context):
        from noetrium_platform.research.execution.workflow.api import (
            WorkflowSurfaceReuseScope,
        )

        if (
            self._surface_registry.reuse_scope(surface_id)
            is not WorkflowSurfaceReuseScope.RUN
        ):
            return self._surface_registry.bind(surface_id, surface_context)

        key = (
            surface_id,
            run_id,
            id(surface_context.bound),
            id(surface_context.participant_sessions),
            id(surface_context.effect_dispatcher),
            id(surface_context.effect_intents),
            id(surface_context.machine_journal),
            id(surface_context.machine_snapshot_store),
        )
        if self._run_surface_key != key or self._run_surface is None:
            self._run_surface = self._surface_registry.bind(
                surface_id,
                surface_context,
            )
            self._run_surface_key = key
        return self._run_surface

    def execute(
        self,
        *,
        bound,
        participant_sessions,
        context,
        task,
        input_kind,
        input_payload,
    ):
        from noetrium_platform.research.execution.workflow.api import (
            TrialCycleExecution,
            WorkflowSurfaceBindingContext,
            workflow_surface_id,
        )

        surface_context = WorkflowSurfaceBindingContext(
            run_id=context.run_id,
            dispatcher=self.dispatcher,
            bound=bound,
            participant_sessions=participant_sessions,
            effect_dispatcher=self.effect_dispatcher,
            effect_intents=self.effect_intents,
            machine_journal=self._machine_journal,
            machine_snapshot_store=self._machine_snapshot_store,
        )
        surface = self._surface_for(
            surface_id=workflow_surface_id(self.trial_protocol),
            run_id=context.run_id,
            surface_context=surface_context,
        )
        result = self.trial_protocol.run(
            surface,
            context,
            task=task,
            input_kind=input_kind,
            input_payload=input_payload,
        )
        if not isinstance(result, TrialCycleExecution):
            raise TypeError("ExperimentTrialProtocol must return TrialCycleExecution")
        return result


class ExperimentComponentBinderForTest:
    def __init__(self, resolver) -> None:
        self._resolver = resolver

    def bind(self, spec, context):
        from noetrium_platform.research.execution.api import BoundParticipants
        from noetrium_platform.research.experimentation.lifecycle.experiment.api import (
            ExperimentParticipantTopology,
        )

        bound = []
        rows = []
        for participant in ExperimentParticipantTopology.from_spec(spec).ordered():
            resolved, operation = self._resolver.resolve(
                participant.runtime_binding(),
                context,
            )
            bound.append(resolved)
            rows.append(operation)
        return BoundParticipants(tuple(bound), tuple(rows))


def build_experiment_runtime_components_for_test(
    *,
    participant_adapters,
    trial_protocol,
    workflow_surface_factories,
    services=None,
    operation_executor=None,
    effect_journal=None,
    operation_state_root=None,
    machine_journal=None,
    machine_snapshot_store=None,
    state_root=None,
):
    """Test-only legacy ExperimentRuntime component assembly.

    Production execution must enter through the canonical Research OS
    composition root. This fixture exists only to pressure-test low-level
    Experimentation contracts after the production parallel root was removed.
    """

    from pathlib import Path

    from noetrium_platform.infrastructure.reliability.effect.api import (
        EffectIntentJournal,
    )
    from noetrium_platform.foundation.kernel.kernel import (
        DirectoryMachineJournal,
        DirectoryMachineSnapshotStore,
        InMemoryMachineJournal,
        OperationExecutor,
    )
    from noetrium_platform.capabilities.participant.core.api import (
        ParticipantLifecycleAdapterRegistry,
    )
    from noetrium_platform.research.experimentation.lifecycle.experiment.api.trial_protocol import (
        trial_protocol_identity,
    )
    from noetrium_platform.capabilities.participant.session.runtime.checkpoint_runtime import (
        ParticipantCheckpointRuntime,
    )
    from noetrium_platform.research.execution.participants import (
        ParticipantCheckpointOperations,
        ParticipantResolutionOperations,
        ParticipantSessionLifecycle,
    )
    from tests_runtime_harness.decision_runtime import (
        DecisionCycleRuntimeForTest,
    )
    from tests_runtime_harness.run_runtime import RunRuntimeForTest
    from noetrium_platform.research.execution.workflow.runtime import (
        DurableKernelOperationDispatcher,
        EffectIntentOperations,
        KernelOperationDispatcher,
        WORKFLOW_RUNTIME_IDENTITY,
    )
    from noetrium_platform.research.execution.operation.command.providers import (
        SQLiteCommandStore,
    )
    from noetrium_platform.research.execution.operation.command.runtime import (
        CommandIntentOwner,
    )
    from noetrium_platform.research.execution.operation.providers import (
        SQLiteOperationStore,
    )
    from noetrium_platform.research.execution.operation.runtime import (
        OperationOwner,
    )

    del EffectIntentJournal
    if state_root is not None:
        root = Path(state_root)
        root.mkdir(parents=True, exist_ok=True)
        if machine_journal is None:
            machine_journal = DirectoryMachineJournal(root / "machine-journal")
        if machine_snapshot_store is None:
            machine_snapshot_store = DirectoryMachineSnapshotStore(
                root / "machine-snapshots"
            )

    shared_machine_journal = (
        machine_journal
        if machine_journal is not None
        else InMemoryMachineJournal()
    )
    kernel_dispatcher = KernelOperationDispatcher(
        operation_executor or OperationExecutor(),
        caller=WORKFLOW_RUNTIME_IDENTITY,
    )
    if effect_journal is None:
        dispatcher = kernel_dispatcher
    else:
        if operation_state_root is None:
            raise ValueError(
                "effectful test runtime requires operation_state_root for "
                "durable Command/Operation authority"
            )
        operation_root = Path(operation_state_root)
        operation_root.mkdir(parents=True, exist_ok=True)
        command_owner = CommandIntentOwner(
            SQLiteCommandStore(operation_root / "commands.sqlite")
        )
        operation_owner = OperationOwner(
            SQLiteOperationStore(operation_root / "operations.sqlite")
        )
        dispatcher = DurableKernelOperationDispatcher(
            kernel_dispatcher,
            commands=command_owner,
            submissions=operation_owner,
            admissions=operation_owner,
            operations=operation_owner,
        )
    adapters = ParticipantLifecycleAdapterRegistry(participant_adapters)
    participant_resolution = ParticipantResolutionOperations(
        kernel_dispatcher,
        adapters,
    )
    binder = ExperimentComponentBinderForTest(participant_resolution)
    lifecycle = ParticipantSessionLifecycle(kernel_dispatcher, services)
    participant_checkpoints = ParticipantCheckpointOperations(
        kernel_dispatcher,
        ParticipantCheckpointRuntime(),
    )
    effect_intents = (
        EffectIntentOperations(kernel_dispatcher, effect_journal)
        if effect_journal is not None
        else None
    )
    trial_cycle = ExperimentTrialCycleExecutorForTest(
        kernel_dispatcher,
        trial_protocol,
        effect_dispatcher=dispatcher,
        effect_intents=effect_intents,
        workflow_surface_factories=workflow_surface_factories,
        machine_journal=shared_machine_journal,
        machine_snapshot_store=machine_snapshot_store,
    )
    return ExperimentRuntimeComponentsForTest(
        trial_protocol_identity(trial_protocol),
        DecisionCycleRuntimeForTest(
            binder,
            lifecycle,
            trial_cycle,
            journal=shared_machine_journal,
            snapshot_store=machine_snapshot_store,
        ),
        RunRuntimeForTest(
            binder,
            lifecycle,
            trial_cycle,
            machine_journal=shared_machine_journal,
            machine_snapshot_store=machine_snapshot_store,
        ),
    )


def build_experiment_runtime_for_test(
    *,
    participant_adapters,
    trial_protocol,
    workflow_surface_factories,
    services=None,
    operation_executor=None,
    cycle_identity_provider=None,
    run_identity_provider=None,
    effect_journal=None,
    operation_state_root=None,
    machine_journal=None,
    machine_snapshot_store=None,
    state_root=None,
):
    """Test-only legacy ExperimentRuntime wrapper over the fixture components."""

    import uuid
    from noetrium_platform.research.experimentation.lifecycle.run.api.identity import RunIdentity

    class _RandomRunIdentityProviderForTest:
        def allocate(self) -> RunIdentity:
            run_id = f"run_{uuid.uuid4().hex[:12]}"
            return RunIdentity(
                run_id,
                f"session_{uuid.uuid4().hex[:12]}",
                run_id,
            )

    from noetrium_platform.research.execution.decision.cycle_identity import (
        RandomDecisionCycleIdentityProvider,
    )

    components = build_experiment_runtime_components_for_test(
        participant_adapters=participant_adapters,
        trial_protocol=trial_protocol,
        workflow_surface_factories=workflow_surface_factories,
        services=services,
        operation_executor=operation_executor,
        effect_journal=effect_journal,
        operation_state_root=operation_state_root,
        machine_journal=machine_journal,
        machine_snapshot_store=machine_snapshot_store,
        state_root=state_root,
    )
    return ExperimentRuntimeForTest(
        components.trial_protocol_identity,
        components.cycle_runtime,
        components.run_runtime,
        run_identity_provider=(
            run_identity_provider
            or _RandomRunIdentityProviderForTest()
        ),
        cycle_identity_provider=(
            cycle_identity_provider
            or RandomDecisionCycleIdentityProvider()
        ),
    )


def context_action_runtime_from_resolver(resolver, **kwargs):
    """Test-only low-level ExperimentRuntime composition.

    Production composition must execute through Research OS. Legacy subsystem
    tests use this helper to pressure-test Experimentation internals directly.
    """

    from noetrium_platform.composition.context_action import (
        context_action_participant_adapters,
    )
    from noetrium_platform.composition.workflows.context_action import (
        ContextActionSurfaceFactory,
        context_action_trial_protocol,
    )

    extra_participant_adapters = kwargs.pop(
        "extra_participant_adapters",
        (),
    )
    extra_surface_factories = kwargs.pop(
        "extra_surface_factories",
        (),
    )
    return build_experiment_runtime_for_test(
        participant_adapters=context_action_participant_adapters(
            resolver,
            extra=extra_participant_adapters,
        ),
        trial_protocol=context_action_trial_protocol(),
        workflow_surface_factories=(
            ContextActionSurfaceFactory(),
            *extra_surface_factories,
        ),
        **kwargs,
    )


def context_action_runtime(methods, environments, **kwargs):
    return context_action_runtime_from_resolver(
        CompositeParticipantResolver(methods, environments),
        **kwargs,
    )


def agent_turn_runtime(agents, **kwargs):
    """Test-only low-level AgentTurn ExperimentRuntime composition."""

    from pathlib import Path

    from noetrium_platform.composition.agent_turn import (
        agent_turn_participant_adapters,
    )
    from noetrium_platform.composition.workflows.agent_turn import (
        AgentTurnSurfaceFactory,
        agent_turn_trial_protocol,
    )
    from noetrium_platform.foundation.kernel.kernel import (
        DirectoryMachineJournal,
        DirectoryMachineSnapshotStore,
        InMemoryMachineJournal,
    )
    from noetrium_platform.research.execution.capability.runtime import (
        ScopedRegistrationRuntimeFactory,
    )

    capability = kwargs.pop("capability_plugins", None)
    runtime = kwargs.pop("runtime_plugins", None)
    extra_participant_adapters = kwargs.pop(
        "extra_participant_adapters",
        (),
    )
    extra_surface_factories = kwargs.pop(
        "extra_surface_factories",
        (),
    )

    state_root = kwargs.get("state_root")
    machine_journal = kwargs.get("machine_journal")
    machine_snapshot_store = kwargs.get("machine_snapshot_store")
    if machine_journal is None:
        if state_root is None:
            machine_journal = InMemoryMachineJournal()
        else:
            root = Path(state_root)
            root.mkdir(parents=True, exist_ok=True)
            machine_journal = DirectoryMachineJournal(root / "machine-journal")
        kwargs["machine_journal"] = machine_journal
    if machine_snapshot_store is None and state_root is not None:
        root = Path(state_root)
        root.mkdir(parents=True, exist_ok=True)
        machine_snapshot_store = DirectoryMachineSnapshotStore(
            root / "machine-snapshots"
        )
        kwargs["machine_snapshot_store"] = machine_snapshot_store

    resolver = CompositeParticipantResolver(agents, capability, runtime)
    runtime_kinds = tuple(
        kind
        for source in (runtime,)
        if source is not None
        for kind in source.kinds()
    )
    return build_experiment_runtime_for_test(
        participant_adapters=agent_turn_participant_adapters(
            resolver,
            runtime_kinds=runtime_kinds,
            include_capability_provider=capability is not None,
            extra=extra_participant_adapters,
        ),
        trial_protocol=agent_turn_trial_protocol(
            journal=machine_journal,
            snapshot_store=machine_snapshot_store,
        ),
        workflow_surface_factories=(
            AgentTurnSurfaceFactory(
                ScopedRegistrationRuntimeFactory(),
            ),
            *extra_surface_factories,
        ),
        **kwargs,
    )
def frozen_binding(
    role: str,
    kind: str,
    participant_id: str,
    implementation_version: str = "1",
    abi_version: str = "1",
    schema_version: str = "1",
    configuration_digest: str = "",
    artifact_digest: str = "",
):
    import hashlib
    from noetrium_platform.capabilities.participant.core.api.contracts import ParticipantImplementationIdentity, ParticipantRuntimeBinding
    resolved_artifact = artifact_digest or hashlib.sha256(
        f"{kind}:{participant_id}:{implementation_version}:{abi_version}:{schema_version}".encode()
    ).hexdigest()
    configuration_seed = configuration_digest or f"{kind}:{participant_id}:configuration"
    resolved_configuration = (
        configuration_seed
        if len(configuration_seed) == 64 and all(ch in "0123456789abcdef" for ch in configuration_seed)
        else hashlib.sha256(configuration_seed.encode()).hexdigest()
    )
    return ParticipantRuntimeBinding(
        role,
        ParticipantImplementationIdentity(
            kind, participant_id, implementation_version, abi_version, schema_version, resolved_artifact
        ),
        runtime_identity_for_test(kind),
        resolved_configuration,
    )


def context_action_runtime_bindings(
    *,
    method_id: str = "m",
    method_version: str = "1",
    method_abi: str = "abi",
    method_schema: str = "1",
    method_config: str = "",
    environment_id: str = "e",
    environment_version: str = "1",
    environment_abi: str = "abi",
    environment_schema: str = "1",
    environment_config: str = "",
):
    return (
        frozen_binding("method", "method", method_id, method_version, method_abi, method_schema, method_config),
        frozen_binding("environment", "environment", environment_id, environment_version, environment_abi, environment_schema, environment_config),
    )


def _frozen_participant_manifest_digests(participant_bindings):
    from noetrium_platform.capabilities.participant.core.api.frozen_manifests import (
        ParticipantImplementationInventory,
        ParticipantRuntimeBindingManifest,
        ParticipantRuntimeInventory,
    )

    bindings = tuple(participant_bindings)
    implementation_inventory = ParticipantImplementationInventory.from_bindings(bindings)
    runtime_inventory = ParticipantRuntimeInventory.from_bindings(bindings)
    binding_manifest = ParticipantRuntimeBindingManifest.build(
        bindings, implementation_inventory, runtime_inventory
    )
    return implementation_inventory.digest(), runtime_inventory.digest(), binding_manifest.digest()


def frozen_runtime_manifest(
    *,
    release_digest: str = "r",
    prompt_generation_digest: str = "p",
    prompt_promotion_digest: str = "pp",
    role_model_manifest_digest: str = "rm",
    qualified_deployment_digests: tuple[str, ...] = (),
    target_host_identity_digest: str = "host",
    participant_bindings=None,
    project_manifest_digest: str = "f" * 64,
    experiment_spec_digest: str = "study",
    command_argv: tuple[str, ...] = ("run",),
    launcher_binary_sha256: str = "a" * 64,
    command_environment_digest: str | None = None,
    config_digests: tuple[tuple[str, str], ...] = (),
    seed_identity: str = "seed",
    composition_plans=None,
):
    from noetrium_platform.research.experimentation.identity import (
        OptionalIdentityFacet,
        ReplayLevel,
        RunResearchSemanticsReference,
    )
    from noetrium_platform.research.experimentation.lifecycle.api import (
        CompositionPlanReference,
        RunLaunchManifest,
    )
    from noetrium_platform.infrastructure.lifecycle.session.api import process_environment_digest

    bindings = context_action_runtime_bindings() if participant_bindings is None else tuple(participant_bindings)
    implementation_inventory_digest, runtime_inventory_digest, binding_manifest_digest = _frozen_participant_manifest_digests(bindings)
    plans = composition_plans
    if plans is None:
        plans = (
            CompositionPlanReference(
                "tests.runtime.composition.v1",
                "system:tests-runtime",
                "platform:platform",
                "a" * 64,
            ),
        )
    return RunLaunchManifest(
        release_digest=release_digest,
        prompt_generation_digest=prompt_generation_digest,
        prompt_promotion_digest=prompt_promotion_digest,
        role_model_manifest_digest=role_model_manifest_digest,
        qualified_deployment_digests=qualified_deployment_digests,
        target_host_identity_digest=target_host_identity_digest,
        participant_implementation_inventory_digest=implementation_inventory_digest,
        participant_runtime_inventory_digest=runtime_inventory_digest,
        participant_binding_manifest_digest=binding_manifest_digest,
        project_manifest_digest=project_manifest_digest,
        experiment_spec_digest=experiment_spec_digest,
        research_semantics=RunResearchSemanticsReference(
            research_plan_digest="a" * 64,
            study_plan_digest="b" * 64,
            measurement_protocol_digest="c" * 64,
            trial_protocol_digest="d" * 64,
            method_implementation_digest="e" * 64,
            intervention=OptionalIdentityFacet(),
            topology=OptionalIdentityFacet(),
            participant_schedule=OptionalIdentityFacet(),
            revision=OptionalIdentityFacet(),
            replay_level=ReplayLevel.EXACT,
        ),
        command_argv=command_argv,
        launcher_binary_sha256=launcher_binary_sha256,
        command_environment_digest=(
            process_environment_digest(())
            if command_environment_digest is None
            else command_environment_digest
        ),
        config_digests=config_digests,
        seed_identity=seed_identity,
        composition_plans=tuple(plans),
    )


def run_launch_manifest(
    *,
    release_digest: str = "r",
    prompt_generation_digest: str = "p",
    role_model_manifest_digest: str = "rm",
    participant_bindings=None,
    experiment_spec_digest: str = "study",
    host_fingerprint: str = "host",
    command_argv: tuple[str, ...] = ("run",),
    config_digests: tuple[tuple[str, str], ...] = (),
    seed_identity: str = "seed",
    prompt_promotion_digest: str = "pp",
):
    return frozen_runtime_manifest(
        release_digest=release_digest,
        prompt_generation_digest=prompt_generation_digest,
        prompt_promotion_digest=prompt_promotion_digest,
        role_model_manifest_digest=role_model_manifest_digest,
        participant_bindings=participant_bindings,
        experiment_spec_digest=experiment_spec_digest,
        target_host_identity_digest=host_fingerprint,
        command_argv=command_argv,
        config_digests=config_digests,
        seed_identity=seed_identity,
    )



def default_method_composition_ports():
    """Build test method ports through the same explicit system boundary as production."""

    from noetrium_platform.capabilities.participant.method.composition import compose_default_method_system
    from noetrium_platform.composition.platform_meta import build_in_memory_platform_meta

    meta = build_in_memory_platform_meta()
    return compose_default_method_system(planner=meta.capability_composition).ports






def repository_architecture_report():
    """Return the immutable architecture report for the current exact checkout.

    The cheap release-manifest digest is recomputed on every call.  Only an
    identical byte-for-byte source tree may reuse the expensive report inside the
    current pytest process, so repository mutation cannot be hidden by the cache.
    """

    from pathlib import Path
    from noetrium_platform.foundation.governance.release.runtime.manifest import build_release_manifest

    root = Path(__file__).resolve().parent
    manifest_digest = build_release_manifest(root).digest()
    return _repository_architecture_report_cached(str(root), manifest_digest)


def _repository_architecture_report_cached(root_text: str, _manifest_digest: str):
    from pathlib import Path
    from noetrium_platform.foundation.governance.architecture import build_architecture_report

    return build_architecture_report(Path(root_text))


from functools import lru_cache as _lru_cache
_repository_architecture_report_cached = _lru_cache(maxsize=4)(_repository_architecture_report_cached)


def recovery_lease_state(path):
    """Test composition for recovery ownership over canonical resource leases."""
    from noetrium_platform.composition.reliability_resources import compose_sqlite_recovery_lease

    return compose_sqlite_recovery_lease(path)
