from __future__ import annotations

from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    study_assignment_digest,
    study_assignment_text,
    study_assignment_repetition,
    study_assignment_workload,
    assignment_workload_digest,
    assignment_workload_task_ids,
    assignment_workload,
    assignment_workload_dependencies_for,
    assignment_workload_prerequisites_for,
    assignment_workload_retry_sources_for,
    validate_assignment_workload,
    execution_policy_environment_session_scope,
    execution_policy_environment_seed_scope,
    execution_policy_replay_level,
    participant_schedule_waves,
    task_content,
    task_id,
)



from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from noetrium_platform.capabilities.api import (
    CapabilityDescriptor,
    CapabilityPort,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.capabilities.environment.category.api import (
    EnvironmentCategoryId,
    EnvironmentCategoryStatus,
)
from noetrium_platform.capabilities.environment.category.composition import (
    default_environment_category_catalog,
)
from noetrium_platform.capabilities.environment.minecraft.composition import (
    compose_official_minecraft_server_artifacts,
)
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactNotFound,
    ArtifactRetention,
)
from noetrium_platform.evidence.artifact.content.composition import (
    compose_artifact_acquisition,
)
from noetrium_platform.evidence.artifact.content.providers.download import (
    open_artifact_http,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    ContentAddressedSingleFlight,
)
from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    DirectoryMachineJournal,
    ExecutionContext,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.foundation.kernel.kernel.durability.stream_digest import sha256_file
from noetrium_platform.infrastructure.resources.directory.api import ManagedDirectoryKind
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import (
    build_local_command_runner,
    build_process_supervisor,
)
from noetrium_platform.infrastructure.reliability.effect.api import EffectIntentJournal
from noetrium_platform.infrastructure.reliability.effect.runtime import (
    sqlite_effect_intent_journal,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.product.research_unit import require_research_root
from noetrium_platform.product.research_traits import (
    TRAIT_ENVIRONMENT,
    TRAIT_PROGRAM,
)
from noetrium_platform.research.execution.capability.runtime import (
    CapabilityInvocationPipelineFactory,
    ScopedRegistrationRuntime,
)
from noetrium_platform.research.execution.workflow.api import (
    ProgramScopedCapabilityPort,
)
from noetrium_platform.research.execution.workflow.runtime import (
    EffectIntentOperations,
)

from .environment_capabilities.lifetime import LifetimeRoutedEnvironmentCapability
from .environment_capabilities.minecraft_local import (
    LocalMinecraftLifetimeSessionController,
    MINECRAFT_LOCAL_IMPLEMENTATION_ID,
    minecraft_lifetime_resource_demand,
)
from .environment_image_runtime import resolve_current_environment_image
from .shared_host_pressure import ResourceCompetitionDemand
from .workflows.agent_turn.capability_effects import CapabilityEffectExecutor
from .workflows.agent_turn.runtime import CapabilityOperationAdapter
from .workflows.agent_turn.runtime import (
    CapabilitySessionBinding,
    StudyCapabilityRouter,
)


@dataclass(slots=True)
class LocalEnvironmentPhysicalRuntime:
    """Own one unique physical Environment authority for a portfolio."""

    lifetime: LifetimeRoutedEnvironmentCapability
    execution_pool: object
    prewarm_group: object
    lifecycle_group: object
    physical_digest: str
    resource_demand: ResourceCompetitionDemand
    _lifetime_closed: bool = False
    _prewarm_group_closed: bool = False
    _lifecycle_group_closed: bool = False
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return

        # Close is an ordered, retryable ownership state machine. A later
        # execution domain is never released while an earlier physical owner
        # may still need it for convergence.
        if not self._lifetime_closed:
            self.lifetime.close()
            self._lifetime_closed = True

        if not self._prewarm_group_closed:
            self.execution_pool.close_workload_group(
                self.prewarm_group,
                cancel_pending=False,
            )
            self._prewarm_group_closed = True

        if not self._lifecycle_group_closed:
            self.execution_pool.close_control_group(
                self.lifecycle_group,
                cancel_pending=False,
            )
            self._lifecycle_group_closed = True

        self._closed = True


@dataclass(slots=True)
class LocalEnvironmentCapabilityRuntime:
    """Own one Program routing view over a shared physical Environment."""

    port: StudyCapabilityRouter
    lifetime: LifetimeRoutedEnvironmentCapability
    resource_demand: ResourceCompetitionDemand
    symbol_digest: str
    implementation_id: str
    effect_journal: EffectIntentJournal
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self.port.close()
        self._closed = True


class ProgramScopedEnvironmentCapabilityPort(ProgramScopedCapabilityPort):
    """One immutable program->capability routing table; callers bind before execution."""

    def __init__(
        self,
        routes: tuple[tuple[str, StudyCapabilityRouter], ...],
    ) -> None:
        if not routes:
            raise ValueError("program-scoped environment capability routes cannot be empty")
        program_ids = tuple(row[0] for row in routes)
        if any(type(value) is not str or not value.strip() for value in program_ids):
            raise ValueError("program-scoped environment program ids must be non-empty")
        if len(program_ids) != len(set(program_ids)):
            raise ValueError("program-scoped environment program ids must be unique")
        self._routes = dict(routes)
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.program-scoped-environment-capabilities.v1",
                "routes": tuple(
                    sorted(
                        (
                            program_id,
                            port.identity_digest,
                        )
                        for program_id, port in routes
                    )
                ),
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def for_program(self, program_id: str) -> CapabilityPort | None:
        if type(program_id) is not str or not program_id.strip():
            raise ValueError("program-scoped capability lookup requires program_id")
        return self._routes.get(program_id)

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        descriptors = []
        for port in self._routes.values():
            try:
                descriptors.append(port.describe(capability_id))
            except (KeyError, LookupError):
                continue
        if not descriptors:
            raise LookupError(capability_id)
        first = descriptors[0]
        core = (
            first.capability_id,
            first.interface_version,
            first.request_schema,
            first.result_schema,
            first.effect_class,
            first.deterministic,
        )
        for row in descriptors[1:]:
            if (
                row.capability_id,
                row.interface_version,
                row.request_schema,
                row.result_schema,
                row.effect_class,
                row.deterministic,
            ) != core:
                raise RuntimeError(
                    "program-scoped capability contract differs across ResearchPrograms: "
                    + capability_id
                )
        return first

    def invoke(self, request: CapabilityRequest, control: ExecutionControlPort) -> CapabilityResult:
        raise RuntimeError(
            "program-scoped capability port must be bound to NoetriumUnit before invocation"
        )

    def drain_operations(self):
        rows = []
        for port in self._routes.values():
            rows.extend(port.drain_operations())
        return tuple(rows)

class ProgramScopedEnvironmentLifetime:
    def __init__(
        self,
        routes: tuple[
            tuple[
                str,
                LifetimeRoutedEnvironmentCapability,
                ResourceCompetitionDemand,
            ],
            ...,
        ],
    ) -> None:
        if not routes:
            raise ValueError("program-scoped environment lifetime routes cannot be empty")
        ids = tuple(row[0] for row in routes)
        if len(ids) != len(set(ids)):
            raise ValueError("program-scoped environment lifetime program ids must be unique")
        if any(type(row[2]) is not ResourceCompetitionDemand for row in routes):
            raise TypeError(
                "program-scoped environment lifetime routes require resource demand"
            )
        self._routes = {
            program_id: lifetime
            for program_id, lifetime, _resource_demand in routes
        }
        self._resource_demands = {
            program_id: resource_demand
            for program_id, _lifetime, resource_demand in routes
        }
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.program-scoped-environment-lifetimes.v2",
                "routes": tuple(
                    sorted(
                        (
                            program_id,
                            lifetime.identity_digest,
                            canonical_digest(resource_demand),
                        )
                        for program_id, lifetime, resource_demand in routes
                    )
                ),
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def for_program(
        self,
        program_id: str,
    ) -> LifetimeRoutedEnvironmentCapability | None:
        if type(program_id) is not str or not program_id.strip():
            raise ValueError("environment lifetime lookup requires program_id")
        return self._routes.get(program_id)

    def resource_demand_for_program(
        self,
        program_id: str,
    ) -> ResourceCompetitionDemand | None:
        if type(program_id) is not str or not program_id.strip():
            raise ValueError("environment resource demand lookup requires program_id")
        return self._resource_demands.get(program_id)

@dataclass(slots=True)
class LocalEnvironmentPortfolioRuntime:
    """Own Program routing views and deduplicated physical Environment authorities."""

    port: ProgramScopedEnvironmentCapabilityPort
    lifetime: ProgramScopedEnvironmentLifetime
    runtimes: tuple[tuple[str, LocalEnvironmentCapabilityRuntime], ...]
    physical_runtimes: tuple[LocalEnvironmentPhysicalRuntime, ...]
    effect_journal: EffectIntentJournal
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        errors: list[BaseException] = []
        for _program_id, runtime in reversed(self.runtimes):
            try:
                runtime.close()
            except BaseException as exc:
                errors.append(exc)
        for runtime in reversed(self.physical_runtimes):
            try:
                runtime.execution_pool.retire_lifecycle_resource(runtime)
            except BaseException as exc:
                errors.append(exc)
        try:
            self.effect_journal.close()
        except BaseException as exc:
            errors.append(exc)
        self._closed = True
        if errors:
            raise BaseExceptionGroup("environment portfolio runtime close failed", errors)


def _environment_trial_participant_context(request) -> dict[str, object]:
    session_scope = execution_policy_environment_session_scope(request.execution_policy)
    seed_scope = execution_policy_environment_seed_scope(request.execution_policy)
    if type(session_scope) is not str or not session_scope.strip() or session_scope != session_scope.strip():
        raise ValueError(
            "trial prewarm environment_session_scope must be canonical non-empty text"
        )
    if type(seed_scope) is not str or not seed_scope.strip() or seed_scope != seed_scope.strip():
        raise ValueError(
            "trial prewarm environment_seed_scope must be canonical non-empty text"
        )

    task_setups: dict[str, Mapping[str, object] | None] = {}
    for definition in request.task_definitions:
        definition_task_id = task_id(definition)
        if definition_task_id in task_setups:
            raise ValueError(
                "environment prewarm task definitions contain duplicate task identity"
            )
        content = task_content(definition)
        if not isinstance(content, Mapping):
            raise ValueError(
                "environment prewarm requires inline immutable task content"
            )
        raw_setup = content.get("environment_setup")
        if raw_setup is not None and not isinstance(raw_setup, Mapping):
            raise TypeError(
                "task environment_setup must be an object when present"
            )
        if raw_setup is None:
            plain_setup = None
        else:
            plain_setup = thaw_json(raw_setup)
            if not isinstance(plain_setup, dict):
                raise TypeError(
                    "task environment_setup must thaw to a JSON object"
                )
        task_setups[definition_task_id] = plain_setup

    workload_task_ids = assignment_workload_task_ids(
        study_assignment_workload(request.assignment)
    )
    if not workload_task_ids:
        raise ValueError("environment prewarm requires at least one workload task")
    if set(task_setups) != set(workload_task_ids):
        raise ValueError(
            "environment prewarm task definitions must exactly cover assignment workload"
        )

    if session_scope != "task":
        setup_digests = {
            canonical_digest(setup) if setup is not None else None
            for setup in task_setups.values()
        }
        if len(setup_digests) != 1:
            raise ValueError(
                f"{session_scope}-scoped environment requires one invariant "
                "environment_setup across its workload"
            )
        selected_setup = task_setups[workload_task_ids[0]]
    else:
        # The task-scoped lifetime is opened for the same canonical workload
        # task that becomes ExecutionContext.task_id below. Never choose setup
        # by caller tuple order: independent graph siblings are intentionally
        # canonicalized and that order may differ from task_definitions.
        selected_setup = task_setups[workload_task_ids[0]]

    participant_context: dict[str, object] = {
        "environment_session_scope": session_scope,
        "environment_seed_scope": seed_scope,
    }
    if selected_setup is not None:
        participant_context["environment_task_setup"] = selected_setup
        pairing_id = selected_setup.get("pairing_id")
        if isinstance(pairing_id, str) and pairing_id.strip():
            participant_context["environment_pairing_id"] = pairing_id.strip()
    return participant_context


def prepare_assignment_environment_trial(
    lifetime: LifetimeRoutedEnvironmentCapability,
    request,
    control: ExecutionControlPort,
) -> None:
    if not isinstance(control, ExecutionControlPort):
        raise TypeError("environment trial prewarm requires ExecutionControlPort")
    control.checkpoint()
    participant_context = _environment_trial_participant_context(request)
    context = replace(
        request.execution_context,
        run_id=request.run_id,
        experiment_id=request.experiment_id,
        span_id=(
            "trial-prewarm:"
            + study_assignment_digest(request.assignment)[:16]
        ),
        parent_span_id=request.execution_context.span_id,
        study_id=study_assignment_text(request.assignment, "study_id"),
        condition_id=study_assignment_text(request.assignment, "variant_id"),
        execution_tenant_id=request.project_id,
        condition_selections=tuple(
            (
                str(row.parameters["factor_id"]),
                str(row.parameters["level_id"]),
            )
            for row in request.intervention_spec.members
        ),
        intervention_values=tuple(
            (
                str(row.parameters["factor_id"]),
                row.parameters["value"],
            )
            for row in request.intervention_spec.members
        ),
        assignment_seed=study_assignment_text(request.assignment, "seed"),
        repetition=study_assignment_repetition(request.assignment),
        participant_schedule=(
            ()
            if request.participant_schedule_spec is None
            else participant_schedule_waves(request.participant_schedule_spec)
        ),
        replay_level=execution_policy_replay_level(request.execution_policy).value,
        participant_context=participant_context,
        lifetime_id=request.assignment_lifetime_id,
        task_id=(
            assignment_workload_task_ids(
                study_assignment_workload(request.assignment)
            )[0]
            if execution_policy_environment_session_scope(request.execution_policy) == "task"
            else None
        ),
        operation_id=request.request_digest,
        component_id="environment-prewarm",
    )
    lifetime.prepare(context, control)


def release_assignment_environment_trial(
    lifetime: LifetimeRoutedEnvironmentCapability,
    request,
) -> None:
    lifetime.release(request.assignment_lifetime_id)

def _environment_definition(program: NoetriumUnit) -> NoetriumUnit | None:
    if type(program) is not NoetriumUnit:
        raise TypeError("environment composition requires NoetriumUnit")
    rows = tuple(
        definition
        for definition in program.symbols
        if definition.has_trait(TRAIT_ENVIRONMENT)
        and isinstance(definition.parameters, Mapping)
        and isinstance(definition.parameters.get("capabilities"), (tuple, list))
        and "environment.act" in tuple(definition.parameters["capabilities"])
    )
    if not rows:
        return None
    if len(rows) != 1:
        raise RuntimeError(
            "one NoetriumUnit may bind environment.act to exactly one ENVIRONMENT definition"
        )
    return rows[0]


def _registered_local_environment_implementations() -> dict[EnvironmentCategoryId, tuple[str, ...]]:
    """Physical runtime implementations owned by this composition.

    Downstream code declares an environment category/capability requirement only.
    This registry is the platform-side executable authority and can grow without
    changing paper code.
    """

    return {
        EnvironmentCategoryId.MINECRAFT: (MINECRAFT_LOCAL_IMPLEMENTATION_ID,),
    }


def _environment_implementation(
    definition: NoetriumUnit,
) -> tuple[dict[str, object], str, EnvironmentCategoryId]:
    if definition.implementation is not None:
        raise RuntimeError(
            "local platform Environment resolver accepts platform-resolved ENVIRONMENT "
            "definitions only; paper-owned implementations require their declared authority"
        )
    if not isinstance(definition.parameters, Mapping):
        raise TypeError("platform-resolved ENVIRONMENT config must be an object")
    config = dict(definition.parameters)
    if "implementation_id" in config:
        raise ValueError(
            "Environment implementation_id is platform-owned; downstream code declares "
            "category/capability semantics only"
        )
    capabilities = config.get("capabilities")
    if (
        type(capabilities) not in {tuple, list}
        or not capabilities
        or any(type(value) is not str or not value.strip() for value in capabilities)
    ):
        raise ValueError(
            "platform-resolved ENVIRONMENT requires non-empty capabilities sequence"
        )
    capabilities = tuple(dict.fromkeys(value.strip() for value in capabilities))
    if "environment.act" not in capabilities:
        raise ValueError(
            "local Environment runtime requires exported capability environment.act"
        )
    category_text = config.get("category_id")
    if type(category_text) is not str or not category_text.strip():
        raise ValueError(
            "platform-resolved ENVIRONMENT requires explicit category_id"
        )
    try:
        category_id = EnvironmentCategoryId(category_text.strip())
    except ValueError as exc:
        raise ValueError(
            f"unknown Environment category_id: {category_text!r}"
        ) from exc

    catalog = default_environment_category_catalog()
    registered = _registered_local_environment_implementations().get(category_id, ())
    candidates = tuple(
        row
        for row in catalog.implementations(category_id)
        if row.status is EnvironmentCategoryStatus.AVAILABLE
        and row.implementation_id in registered
    )
    if not candidates:
        raise RuntimeError(
            "no platform-qualified local Environment implementation is available for "
            f"category={category_id.value!r}"
        )
    if len(candidates) != 1:
        # Multiple executable providers require a platform-side qualification/
        # telemetry selector; never push the choice back into paper code.
        raise RuntimeError(
            "Environment category has multiple platform-executable implementations "
            "without a unique platform qualification winner: "
            + repr(tuple(sorted(row.implementation_id for row in candidates)))
        )
    implementation = candidates[0]
    return config, implementation.implementation_id, category_id


def _materialize_minecraft_server_asset(
    *,
    context,
    version: str,
    asset_root: Path,
) -> tuple[Path, str]:
    """Materialize one immutable official server asset through platform authority.

    The host-scoped artifact catalog is the durable truth. A verified local hit
    performs no metadata or download network I/O; misses are globally fenced
    before resolving Mojang metadata and publishing the exact content.
    """

    asset_root.mkdir(parents=True, exist_ok=True)
    destination = asset_root / "server.jar"
    artifact_id = f"minecraft.server.{version}"
    operation_id = canonical_digest(
        {
            "schema": "noetrium.minecraft-server-asset-materialization.v2",
            "minecraft_version": version,
        }
    )
    platform_artifacts = context.runtime.management.platform_meta.artifacts
    singleflight = ContentAddressedSingleFlight(
        context.runtime.management.physical_directories.layout.root(ManagedDirectoryKind.LOCKS)
        / "global-single-flight"
    )

    with singleflight.producer("artifact-materialization", operation_id):
        try:
            registered = platform_artifacts.get(artifact_id)
        except ArtifactNotFound:
            registered = None
        if registered is not None:
            if (
                registered.kind is not ArtifactKind.RUNTIME
                or registered.scope != PLATFORM_SCOPE
                or registered.retention is not ArtifactRetention.PERMANENT
                or registered.producer_component_id
                != "environment.minecraft.server-artifact"
            ):
                raise RuntimeError(
                    "Minecraft server artifact platform authority identity drift"
                )
            if destination.is_file():
                observed_digest, _size = sha256_file(destination)
                if observed_digest == registered.digest:
                    return destination, registered.digest

        acquisition = compose_artifact_acquisition()
        provider = compose_official_minecraft_server_artifacts(
            acquisition=acquisition.acquirer,
            metadata_opener=open_artifact_http,
        ).provider
        result = provider.acquire(
            version,
            destination=str(destination),
            scope=PLATFORM_SCOPE,
            producer_operation_id=operation_id,
            replace_existing=destination.exists(),
        )
        registered = platform_artifacts.put(result.record)
        if registered.digest != result.record.digest:
            raise RuntimeError("Minecraft server artifact registry digest drift")
        if not destination.is_file():
            raise RuntimeError(
                "Minecraft server artifact acquisition did not publish server.jar"
            )
        observed_digest, _size = sha256_file(destination)
        if observed_digest != registered.digest:
            raise RuntimeError(
                "Minecraft server artifact content digest drift after publication"
            )
        return destination, registered.digest


def _environment_physical_digest(definition: NoetriumUnit) -> str:
    config, implementation_id, category_id = _environment_implementation(definition)
    return canonical_digest(
        {
            "schema": "noetrium.environment-physical-runtime.v1",
            "implementation_id": implementation_id,
            "category_id": category_id.value,
            "configuration": config,
        }
    )


def _compose_physical_environment_runtime(
    definition: NoetriumUnit,
    context,
    *,
    realization_cache: dict[
        tuple[str, str, str],
        tuple[str, str, Path, str],
    ] | None = None,
) -> LocalEnvironmentPhysicalRuntime:
    config, implementation_id, category_id = _environment_implementation(definition)
    if implementation_id != MINECRAFT_LOCAL_IMPLEMENTATION_ID:
        raise RuntimeError(
            "local Environment execution has no registered runtime factory for "
            f"{implementation_id!r}; category={category_id.value!r}"
        )
    version = str(config.get("minecraft_version", "")).strip()
    if not version:
        raise RuntimeError(
            "minecraft.mineflayer Environment requires explicit minecraft_version"
        )
    physical_digest = _environment_physical_digest(definition)
    physical_environment_root = (
        context.runtime.management.physical_directories.layout.root(
            ManagedDirectoryKind.RUNTIME
        )
        / "environment-fabric"
        / "minecraft"
    )
    minecraft_resource_demand = minecraft_lifetime_resource_demand()
    # Environment preparation is synchronous child work of an Experiment node.
    # It must never share the orchestration worker domain with the parent graph
    # task: if every orchestration worker is occupied by parents waiting for
    # prewarm, queued prewarm children can never run (nested-pool starvation).
    # Prewarm is Experiment child work and completes before the workload DAG.
    # Keep it in the independent workload domain; UnitActivation remains one
    # adjacent layer lower in Machine. No synchronous parent therefore waits on
    # a child scheduled into the same BLOCKING_IO provider.
    prewarm_group = context.execution_pool.open_workload_group(
        "research-environment-prewarm:" + physical_digest[:24] + ":" + context.execution_pool.owner_generation_id[:16],
        tenant_id=context.execution_tenant_id,
        resource_id="environment-prewarm:" + physical_digest[:24],
        resource_demand=minecraft_resource_demand,
    )
    lifecycle_group = context.execution_pool.open_control_group(
        "research-environment-lifecycle:" + physical_digest[:24] + ":" + context.execution_pool.owner_generation_id[:16],
        tenant_id=context.execution_tenant_id,
        resource_id="environment-lifecycle:" + physical_digest[:24],
    )
    task_group = context.execution_pool.open_capability_io_group(
        "research-environment:" + physical_digest[:24] + ":" + context.execution_pool.owner_generation_id[:16],
        tenant_id=context.execution_tenant_id,
        resource_demand=None,
    )
    runner = build_local_command_runner(
        lifecycle_group,
        task_namespace="research-environment-lifecycle",
    )
    process_supervisor = build_process_supervisor(
        lifecycle_group,
        task_namespace="research-environment-process",
    )
    realization_key = (implementation_id, category_id.value, version)
    cached_realization = (
        None if realization_cache is None else realization_cache.get(realization_key)
    )
    platform_meta = context.runtime.management.platform_meta
    resource_authority = platform_meta.resource_authority
    docker_provider = context.runtime.management.docker_provider
    environment_catalog = platform_meta.environments
    if cached_realization is None:
        image, image_digest = resolve_current_environment_image(
            runner,
            category_id=category_id.value,
        )
        asset_root = (
            context.runtime.management.durable_directories.layout.root(
                ManagedDirectoryKind.STATE
            )
            / "environment-assets"
            / ("minecraft-" + version)
        )
        _asset_path, asset_digest = _materialize_minecraft_server_asset(
            context=context,
            version=version,
            asset_root=asset_root,
        )
        if realization_cache is not None:
            realization_cache[realization_key] = (
                image,
                image_digest,
                asset_root,
                asset_digest,
            )
    else:
        image, image_digest, asset_root, asset_digest = cached_realization

    lifetime_controller = LocalMinecraftLifetimeSessionController(
        environment_config=config,
        state_root=physical_environment_root,
        asset_root=asset_root,
        asset_digest=asset_digest,
        resource_authority=resource_authority,
        docker_provider=docker_provider,
        compute_inventory=platform_meta.compute_inventory,
        endpoint_candidates=platform_meta.endpoint_candidates,
        endpoint_probe=platform_meta.endpoint_probe,
        gpu_runtime_observer=platform_meta.gpu_runtime_observer,
        host_runtime_observer=platform_meta.host_runtime_observer,
        environment_catalog=environment_catalog,
        image=image,
        image_digest=image_digest,
        runner=runner,
        operating_system=context.runtime.management.host.operating_system,
        process_supervisor=process_supervisor,
        task_group=task_group,
        lifecycle_task_group=lifecycle_group,
        prewarm_task_group=prewarm_group,
        resource_lease_guard_factory=context.execution_pool.resource_lease_guard_factory(
            resource_authority
        ),
        owner_generation_id=context.execution_pool.owner_generation_id,
        reconcile_shared_fabric=True,
    )
    session_scope = str(config.get("session_scope", "assignment")).strip()
    lifetime = LifetimeRoutedEnvironmentCapability(
        lifetime_controller,
        session_scope=session_scope,
    )
    physical_runtime = LocalEnvironmentPhysicalRuntime(
        lifetime,
        context.execution_pool,
        prewarm_group,
        lifecycle_group,
        physical_digest,
        minecraft_resource_demand,
    )
    try:
        context.execution_pool.register_lifecycle_resource(physical_runtime)
    except BaseException:
        physical_runtime.close()
        raise
    return physical_runtime


def _compose_program_environment_runtime(
    program: NoetriumUnit,
    definition: NoetriumUnit,
    context,
    *,
    program_scope_id: str,
    effect_journal: EffectIntentJournal,
    physical_runtime: LocalEnvironmentPhysicalRuntime,
) -> LocalEnvironmentCapabilityRuntime:
    del program
    _config, implementation_id, category_id = _environment_implementation(definition)
    if implementation_id != MINECRAFT_LOCAL_IMPLEMENTATION_ID:
        raise RuntimeError(
            "local Environment execution has no registered runtime factory for "
            f"{implementation_id!r}; category={category_id.value!r}"
        )
    if physical_runtime.physical_digest != _environment_physical_digest(definition):
        raise RuntimeError(
            "Program Environment route was bound to a different physical authority"
        )
    lifetime = physical_runtime.lifetime
    dispatcher = context.runtime.operation_runtime.dispatcher
    operations = CapabilityOperationAdapter(dispatcher)
    effect_dispatcher = context.runtime.operation_runtime.kernel_dispatcher
    effect_operations = CapabilityOperationAdapter(effect_dispatcher)
    effect_intents = EffectIntentOperations(effect_journal)
    effect_executor = CapabilityEffectExecutor(
        effect_dispatcher,
        effect_intents,
        effect_operations,
    )
    provider_component = ComponentIdentity(
        "capability_provider.environment",
        implementation_id,
        "1",
        "1",
        lifetime.identity_digest,
    )
    consumer_component = ComponentIdentity(
        "method.environment.consumer",
        program_scope_id,
        "1",
        "1",
        canonical_digest(
            {
                "schema": "noetrium.method-environment-consumer.v2",
                "program_scope_id": program_scope_id,
                "environment": lifetime.identity_digest,
            }
        ),
    )
    router = StudyCapabilityRouter(
        operations,
        (
            CapabilitySessionBinding(
                provider_component,
                lifetime,
                source_role="environment",
            ),
        ),
        effect_executor=effect_executor,
        consumer_component=consumer_component,
        pipeline=CapabilityInvocationPipelineFactory(
            DirectoryMachineJournal(
                context.state_root / "machine-state" / "unit-journal"
            )
        ).create(),
        scope=ScopedRegistrationRuntime(
            "research-environment-capability:"
            + canonical_digest(
                {
                    "program_scope_id": program_scope_id,
                    "environment": lifetime.identity_digest,
                }
            )[:24]
        ),
    )
    return LocalEnvironmentCapabilityRuntime(
        router,
        lifetime,
        physical_runtime.resource_demand,
        definition.symbol_digest,
        implementation_id,
        effect_journal,
    )

def compose_local_environment_capability_runtime(
    portfolio: NoetriumUnit,
    context,
) -> LocalEnvironmentPortfolioRuntime | None:
    require_research_root(portfolio)
    definitions = tuple(
        (graph_path, program, definition)
        for graph_path, program in portfolio.paths_with_schema(TRAIT_PROGRAM)
        for definition in (_environment_definition(program),)
        if definition is not None
    )
    if not definitions:
        return None

    # External-effect truth is one portfolio Authority, not one writer per
    # Program. Program identity remains in each router/ExecutionContext while
    # every effect transition shares the same serialized durable journal.
    effect_journal = sqlite_effect_intent_journal(
        context.state_root / "effect-intents" / "environment.sqlite"
    )
    rows: list[tuple[str, LocalEnvironmentCapabilityRuntime]] = []
    physicals: dict[str, LocalEnvironmentPhysicalRuntime] = {}
    realization_cache: dict[
        tuple[str, str, str],
        tuple[str, str, Path, str],
    ] = {}
    try:
        for graph_path, program, definition in definitions:
            program_scope_id = "::".join(graph_path)
            physical_digest = _environment_physical_digest(definition)
            physical = physicals.get(physical_digest)
            if physical is None:
                physical = _compose_physical_environment_runtime(
                    definition,
                    context,
                    realization_cache=realization_cache,
                )
                physicals[physical_digest] = physical
            rows.append(
                (
                    program_scope_id,
                    _compose_program_environment_runtime(
                        program,
                        definition,
                        context,
                        program_scope_id=program_scope_id,
                        effect_journal=effect_journal,
                        physical_runtime=physical,
                    ),
                )
            )
    except BaseException as primary:
        cleanup_errors: list[BaseException] = []
        for _program_id, runtime in reversed(rows):
            try:
                runtime.close()
            except BaseException as exc:
                cleanup_errors.append(exc)
        for runtime in reversed(tuple(physicals.values())):
            try:
                runtime.execution_pool.retire_lifecycle_resource(runtime)
            except BaseException as exc:
                cleanup_errors.append(exc)
        try:
            effect_journal.close()
        except BaseException as exc:
            cleanup_errors.append(exc)
        if cleanup_errors:
            raise ExceptionGroup(
                "environment portfolio materialization failed and cleanup did not converge",
                [primary, *cleanup_errors],
            ) from primary
        raise

    rows_tuple = tuple(sorted(rows, key=lambda row: row[0]))
    physicals_tuple = tuple(physicals[key] for key in sorted(physicals))
    return LocalEnvironmentPortfolioRuntime(
        ProgramScopedEnvironmentCapabilityPort(
            tuple((program_id, runtime.port) for program_id, runtime in rows_tuple)
        ),
        ProgramScopedEnvironmentLifetime(
            tuple(
                (
                    program_id,
                    runtime.lifetime,
                    runtime.resource_demand,
                )
                for program_id, runtime in rows_tuple
            )
        ),
        rows_tuple,
        physicals_tuple,
        effect_journal,
    )


__all__ = [
    "LocalEnvironmentPhysicalRuntime",
    "LocalEnvironmentCapabilityRuntime",
    "LocalEnvironmentPortfolioRuntime",
    "ProgramScopedEnvironmentCapabilityPort",
    "ProgramScopedEnvironmentLifetime",
    "compose_local_environment_capability_runtime",
    "prepare_assignment_environment_trial",
    "release_assignment_environment_trial",
]
