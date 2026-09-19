from __future__ import annotations

from noetrium_platform.research.experimentation.experiment.api import ExperimentModelRoleSpec, ExperimentParticipantSpec, ExperimentSpec
from noetrium_platform.capabilities.participant.core.api.contracts import (
    ParticipantImplementationIdentity, ParticipantRuntimeBinding, ParticipantSessionRuntimeIdentity,
)
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantRuntimeHandle


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
                "noetrium_platform.research.execution.workflow.implementations.context_action",
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
    from noetrium_platform.capabilities.environment.runtime.api import action_request_digest

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

class EmptyWorkflowSurfaceFactory:
    surface_id = "empty.operations.v1"

    @staticmethod
    def bind(context):
        del context
        return object()


def context_action_runtime(methods, environments, **kwargs):
    from noetrium_platform.composition.context_action import compose_context_action_runtime
    return compose_context_action_runtime(CompositeParticipantResolver(methods, environments), **kwargs)


def agent_turn_runtime(agents, **kwargs):
    from noetrium_platform.composition.agent_turn import compose_agent_turn_runtime
    capability = kwargs.pop("capability_plugins", None)
    runtime = kwargs.pop("runtime_plugins", None)
    resolver = CompositeParticipantResolver(agents, capability, runtime)
    runtime_kinds = tuple(
        kind for source in (runtime,) if source is not None for kind in source.kinds()
    )
    return compose_agent_turn_runtime(
        resolver,
        runtime_kinds=runtime_kinds,
        include_capability_provider=capability is not None,
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
    from noetrium_platform.research.experimentation.run.manifest.api import (
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
    from noetrium_platform.infrastructure.reliability.recovery.composition import (
        compose_sqlite_recovery_lease,
    )

    return compose_sqlite_recovery_lease(path)
