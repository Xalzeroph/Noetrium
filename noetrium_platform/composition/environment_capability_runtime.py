from __future__ import annotations

from dataclasses import dataclass
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
from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    DirectoryMachineJournal,
    canonical_digest,
)
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import (
    build_local_command_runner,
    build_process_supervisor,
)
from noetrium_platform.infrastructure.reliability.effect.runtime import (
    sqlite_effect_intent_journal,
)
from noetrium_platform.product.research_os import (
    ResearchDefinition,
    ResearchDefinitionKind,
    ResearchPortfolio,
    ResearchProgram,
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
    LocalMinecraftLifetimeSessionAuthority,
)
from .environment_image_runtime import resolve_current_environment_image
from .workflows.agent_turn.capability_effects import CapabilityEffectExecutor
from .workflows.agent_turn.capability_operations import CapabilityOperationAdapter
from .workflows.agent_turn.capability_routing import (
    CapabilitySessionBinding,
    StudyCapabilityRouter,
)


@dataclass(frozen=True, slots=True)
class LocalEnvironmentCapabilityRuntime:
    port: StudyCapabilityRouter
    lifetime: LifetimeRoutedEnvironmentCapability
    definition_digest: str
    implementation_id: str


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

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        if len(self._routes) == 1:
            return next(iter(self._routes.values())).invoke(request)
        raise RuntimeError(
            "program-scoped capability port must be bound to ResearchProgram before invocation"
        )

    def drain_operations(self):
        rows = []
        for port in self._routes.values():
            rows.extend(port.drain_operations())
        return tuple(rows)

    def close(self) -> None:
        errors = []
        for port in self._routes.values():
            try:
                port.close()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup("program-scoped capability close failed", errors)


class ProgramScopedEnvironmentLifetime:
    def __init__(
        self,
        routes: tuple[tuple[str, LifetimeRoutedEnvironmentCapability], ...],
    ) -> None:
        if not routes:
            raise ValueError("program-scoped environment lifetime routes cannot be empty")
        ids = tuple(row[0] for row in routes)
        if len(ids) != len(set(ids)):
            raise ValueError("program-scoped environment lifetime program ids must be unique")
        self._routes = dict(routes)
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.program-scoped-environment-lifetimes.v1",
                "routes": tuple(
                    sorted(
                        (program_id, lifetime.identity_digest)
                        for program_id, lifetime in routes
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

    def close(self) -> None:
        errors = []
        for lifetime in self._routes.values():
            try:
                lifetime.close()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup("program-scoped environment lifetime close failed", errors)


@dataclass(frozen=True, slots=True)
class LocalEnvironmentPortfolioRuntime:
    port: ProgramScopedEnvironmentCapabilityPort
    lifetime: ProgramScopedEnvironmentLifetime
    runtimes: tuple[tuple[str, LocalEnvironmentCapabilityRuntime], ...]


class AssignmentLifetimeFinalizingTrialProvider:
    def __init__(self, delegate, lifetime: LifetimeRoutedEnvironmentCapability) -> None:
        self._delegate = delegate
        self._lifetime = lifetime
        self.protocol_identity = delegate.protocol_identity
        self.identity_digest = canonical_digest(
            {
                "schema": "noetrium.assignment-lifetime-finalizing-trial-provider.v1",
                "delegate": delegate.identity_digest,
                "environment": lifetime.identity_digest,
            }
        )

    def run_trial(self, request):
        try:
            return self._delegate.run_trial(request)
        finally:
            self._lifetime.release(request.assignment_lifetime_id)


def _environment_definition(program: ResearchProgram) -> ResearchDefinition | None:
    if type(program) is not ResearchProgram:
        raise TypeError("environment composition requires ResearchProgram")
    rows = tuple(
        definition
        for definition in program.definitions
        if definition.kind is ResearchDefinitionKind.ENVIRONMENT
        and isinstance(definition.config, Mapping)
        and definition.config.get("required_capability") == "environment.act"
    )
    if not rows:
        return None
    if len(rows) != 1:
        raise RuntimeError(
            "one ResearchProgram may bind environment.act to exactly one ENVIRONMENT definition"
        )
    return rows[0]


def _environment_implementation(
    definition: ResearchDefinition,
) -> tuple[dict[str, object], str, EnvironmentCategoryId]:
    if definition.implementation is not None:
        raise RuntimeError(
            "local platform Environment resolver accepts platform-resolved ENVIRONMENT "
            "definitions only; paper-owned implementations require their declared authority"
        )
    if not isinstance(definition.config, Mapping):
        raise TypeError("platform-resolved ENVIRONMENT config must be an object")
    config = dict(definition.config)
    if config.get("required_capability") != "environment.act":
        raise ValueError("local Environment runtime requires capability environment.act")
    category_text = config.get("category_id")
    implementation_id = config.get("implementation_id")
    if type(category_text) is not str or not category_text.strip():
        raise ValueError(
            "platform-resolved ENVIRONMENT requires explicit category_id"
        )
    if type(implementation_id) is not str or not implementation_id.strip():
        raise ValueError(
            "platform-resolved ENVIRONMENT requires explicit implementation_id"
        )
    try:
        category_id = EnvironmentCategoryId(category_text.strip())
    except ValueError as exc:
        raise ValueError(
            f"unknown Environment category_id: {category_text!r}"
        ) from exc
    catalog = default_environment_category_catalog()
    implementation = catalog.implementation(implementation_id.strip())
    if implementation.category_id is not category_id:
        raise ValueError(
            "Environment implementation/category identity mismatch: "
            f"{implementation.implementation_id} belongs to "
            f"{implementation.category_id.value}, not {category_id.value}"
        )
    if implementation.status is not EnvironmentCategoryStatus.AVAILABLE:
        raise RuntimeError(
            "Environment implementation is contract-only and cannot execute locally: "
            + implementation.implementation_id
        )
    return config, implementation.implementation_id, category_id


def _compose_program_environment_runtime(
    program: ResearchProgram,
    definition: ResearchDefinition,
    context,
) -> LocalEnvironmentCapabilityRuntime:
    config, implementation_id, category_id = _environment_implementation(definition)
    if implementation_id != "minecraft.mineflayer":
        raise RuntimeError(
            "local Environment execution has no registered runtime factory for "
            f"{implementation_id!r}; category={category_id.value!r}"
        )

    version = str(config.get("minecraft_version", "")).strip()
    if not version:
        raise RuntimeError(
            "minecraft.mineflayer Environment requires explicit minecraft_version"
        )
    program_root = (
        context.state_root
        / "environment-programs"
        / program.program_id
        / definition.definition_digest
    )
    task_group = context.execution_pool.open_capability_io_group(
        "research-environment:"
        + canonical_digest(
            {
                "program_id": program.program_id,
                "definition_digest": definition.definition_digest,
            }
        )[:24],
        resource_demand=None,
    )
    runner = build_local_command_runner(
        task_group,
        task_namespace="research-environment-docker",
    )
    process_supervisor = build_process_supervisor(
        task_group,
        task_namespace="research-environment-process",
    )
    image, image_digest = resolve_current_environment_image(
        runner,
        category_id=category_id.value,
    )

    endpoint_allocations = (
        context.runtime.management.platform_meta.endpoint_allocations
    )
    docker_authority = context.runtime.management.docker_containers
    environment_instances = (
        context.runtime.management.platform_meta.environment_instance_leases
    )
    lifetime_authority = LocalMinecraftLifetimeSessionAuthority(
        environment_config=config,
        state_root=program_root,
        asset_root=(
            context.state_root
            / "authorities"
            / "environments"
            / ("minecraft-" + version)
            / "assets"
        ),
        endpoint_allocations=endpoint_allocations,
        endpoint_lease_guard_factory=(
            context.execution_pool.endpoint_lease_guard_factory(endpoint_allocations)
        ),
        docker_authority=docker_authority,
        docker_lease_guard_factory=(
            context.execution_pool.docker_container_lease_guard_factory(
                docker_authority
            )
        ),
        environment_instance_authority=environment_instances,
        environment_instance_lease_guard_factory=(
            context.execution_pool.environment_instance_lease_guard_factory(
                environment_instances
            )
        ),
        image=image,
        image_digest=image_digest,
        runner=runner,
        operating_system=context.runtime.management.host.operating_system,
        process_supervisor=process_supervisor,
        task_group=task_group,
        owner_generation_id=context.execution_pool.owner_generation_id,
    )
    lifetime = LifetimeRoutedEnvironmentCapability(lifetime_authority)

    dispatcher = context.runtime.operation_runtime.dispatcher
    operations = CapabilityOperationAdapter(dispatcher)
    effect_intents = EffectIntentOperations(
        dispatcher,
        sqlite_effect_intent_journal(
            context.state_root / "effect-intents" / "environment.sqlite"
        ),
    )
    effect_executor = CapabilityEffectExecutor(
        dispatcher,
        effect_intents,
        operations,
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
        program.program_id,
        "1",
        "1",
        canonical_digest(
            {
                "schema": "noetrium.method-environment-consumer.v2",
                "program_id": program.program_id,
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
                context.state_root / "machine-state" / "program-journal"
            )
        ).create(),
        scope=ScopedRegistrationRuntime(
            "research-environment-capability:"
            + canonical_digest(
                {
                    "program_id": program.program_id,
                    "environment": lifetime.identity_digest,
                }
            )[:24]
        ),
    )
    return LocalEnvironmentCapabilityRuntime(
        router,
        lifetime,
        definition.definition_digest,
        implementation_id,
    )


def compose_local_environment_capability_runtime(
    portfolio: ResearchPortfolio,
    context,
) -> LocalEnvironmentPortfolioRuntime | None:
    if type(portfolio) is not ResearchPortfolio:
        raise TypeError("Environment capability composition requires ResearchPortfolio")
    rows: list[tuple[str, LocalEnvironmentCapabilityRuntime]] = []
    for program in portfolio.programs:
        definition = _environment_definition(program)
        if definition is None:
            continue
        rows.append(
            (
                program.program_id,
                _compose_program_environment_runtime(program, definition, context),
            )
        )
    if not rows:
        return None
    rows_tuple = tuple(sorted(rows, key=lambda row: row[0]))
    return LocalEnvironmentPortfolioRuntime(
        ProgramScopedEnvironmentCapabilityPort(
            tuple((program_id, runtime.port) for program_id, runtime in rows_tuple)
        ),
        ProgramScopedEnvironmentLifetime(
            tuple(
                (program_id, runtime.lifetime)
                for program_id, runtime in rows_tuple
            )
        ),
        rows_tuple,
    )


__all__ = [
    "AssignmentLifetimeFinalizingTrialProvider",
    "LocalEnvironmentCapabilityRuntime",
    "LocalEnvironmentPortfolioRuntime",
    "ProgramScopedEnvironmentCapabilityPort",
    "ProgramScopedEnvironmentLifetime",
    "compose_local_environment_capability_runtime",
]
