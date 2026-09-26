from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_local_command_runner

from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayout, DirectoryLayoutPort, DirectoryManagementAuthorities
from noetrium_platform.infrastructure.resources.directory.runtime import build_local_directory_authorities
from noetrium_platform.capabilities.model.api import ModelAuthorities, ModelRevisionAuthorityPort
from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentLogs
from noetrium_platform.capabilities.model.asset.providers import HuggingFaceCliModelSource
from noetrium_platform.capabilities.model.asset.runtime import LocalModelAssetStorage, ModelAssetManager, ModelAssetRegistry
from noetrium_platform.capabilities.model.composition import DeploymentModelAssetReferences
from noetrium_platform.capabilities.model.catalog.revision.composition import sqlite_revision_authority
from noetrium_platform.capabilities.model.deployment.composition import LocalModelReplicaPoolRuntime
from noetrium_platform.capabilities.model.assignment.runtime import ModelAssignmentManager
from noetrium_platform.capabilities.model.deployment.runtime import (
    AppliedModelDeploymentStore,
    DurableModelAutoRecoveryAuthority,
    FileModelControllerStateStore,
    ModelDesiredStateController,
    ModelDeploymentCatalog,
    ModelDeploymentLogReader,
    ModelDeploymentRegistry,
    ModelDeploymentRuntime,
    ModelLaunchMaterializer,
    ModelFleetRuntime,
    ModelResourceView,
)
from noetrium_platform.capabilities.model.qualification.composition import (
    DeploymentQualificationAuthorities,
    build_local_deployment_qualification,
)
from noetrium_platform.infrastructure.resources.compute.api import ComputeSchedulerPort
from noetrium_platform.infrastructure.resources.compute.providers import LocalHostRuntimeObserver, NvidiaSmiGpuRuntimeObserver
from noetrium_platform.composition.resource_probes import LocalCommandResourceProbe
from noetrium_platform.composition.model_qualification import QUALIFICATION_INDEX_WORKER_PATH
from noetrium_platform.infrastructure.lifecycle.python.api import PythonEnvironmentAuthorities
from noetrium_platform.capabilities.environment.catalog.api import ExecutionEnvironmentCatalogPort
from noetrium_platform.infrastructure.resources.container.providers import (
    DockerCliManagedContainerProvider,
    discover_docker_root,
)
from noetrium_platform.infrastructure.resources.container.runtime import (
    DockerContainerLeaseAuthority,
)
from noetrium_platform.foundation.scope.api import ScopeRegistryPort
from noetrium_platform.infrastructure.lifecycle.host.api import OperatingSystemRoute
from noetrium_platform.infrastructure.lifecycle.python.runtime import (
    CondaEnvironmentBackend,
    build_python_environment_authorities,
    SubprocessEnvironmentCommandRunner,
    VenvEnvironmentBackend,
)
from noetrium_platform.infrastructure.lifecycle.service.api import (
    MaterializedServiceEnvironment,
    ServiceLaunchContract,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime import (
    DirectoryCapturePathProvider,
    ExactServiceRuntimeEndpoint,
    HttpEndpointReadinessProbe,
    LocalServiceProcessAdapter,
    ProcessAliveReadinessProbe,
    StaticServiceEnvironmentProvider,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_intent_store import DirectoryServiceStartIntentStore
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore

from noetrium_platform.infrastructure.lifecycle.service.composition import compose_local_process_backend, build_service_supervisor
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_process_supervisor
from noetrium_platform.infrastructure.lifecycle.host.composition import HostComposition, compose_local_host
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.platform_meta import (
    PlatformMetaAuthorities,
    build_platform_meta,
)
from noetrium_platform.infrastructure.resources.compute.composition import (
    discover_local_compute_host,
)


@dataclass(frozen=True, slots=True)
class ManagementPlaneAuthorities:
    scopes: ScopeRegistryPort
    directories: DirectoryManagementAuthorities
    execution_environments: ExecutionEnvironmentCatalogPort
    python_environments: PythonEnvironmentAuthorities
    models: ModelAuthorities
    model_revisions: ModelRevisionAuthorityPort
    host: HostComposition
    compute_scheduler: ComputeSchedulerPort
    deployment_qualification: DeploymentQualificationAuthorities
    docker_containers: DockerContainerLeaseAuthority
    platform_meta: PlatformMetaAuthorities


class LocalModelServiceRuntimeFactory:
    """Composition-only factory for many independently managed local model services."""

    def __init__(
        self,
        directories: DirectoryLayoutPort,
        *,
        operating_system: OperatingSystemRoute,
        task_group: TaskGroupPort,
    ) -> None:
        self._directories = directories
        self._operating_system = operating_system
        self._task_group = task_group
        self._state_root = directories.layout.state / "model-services"
        self._intent_root = directories.layout.runtime / "model-service-start-intents"
        self._capture_root = directories.layout.logs / "model-services"

    def open(
        self,
        contract: ServiceLaunchContract,
        *,
        environment: tuple[tuple[str, str], ...],
        readiness_url: str | None,
    ) -> ExactServiceRuntimeEndpoint:
        service_key = self._safe(contract.service_id)
        materialized = MaterializedServiceEnvironment(
            variables=environment,
            evidence_ref=f"model-serving-env:{contract.environment_digest}",
        )
        provider = StaticServiceEnvironmentProvider((materialized,))
        backend = compose_local_process_backend(
            self._operating_system,
            process_supervisor=build_process_supervisor(self._task_group),
        )
        readiness = (
            HttpEndpointReadinessProbe(self._task_group, readiness_url)
            if readiness_url
            else ProcessAliveReadinessProbe(self._task_group)
        )
        adapter = LocalServiceProcessAdapter(
            provider,
            DirectoryCapturePathProvider(self._capture_root),
            backend,
            readiness,
        )
        contract_key = contract.digest()
        state = FileServiceStateStore(self._state_root / service_key / contract_key / "state.json")
        intents = DirectoryServiceStartIntentStore(self._intent_root / service_key / contract_key)
        return ExactServiceRuntimeEndpoint(build_service_supervisor(state, intents, adapter))


    def logs(self, contract: ServiceLaunchContract, *, deployment_id: str) -> ModelDeploymentLogs:
        paths = DirectoryCapturePathProvider(self._capture_root).paths(contract)
        return ModelDeploymentLogs(deployment_id, paths.stdout_path, paths.stderr_path)

    @staticmethod
    def _safe(value: str) -> str:
        return value.replace("/", "_").replace("\\", "_")



def discover_local_docker_root(
    task_group: TaskGroupPort,
    *,
    docker_executable: str = "docker",
) -> Path | None:
    """Discover Docker storage through the structured control command runner."""

    return discover_docker_root(
        build_local_command_runner(task_group),
        docker_executable=docker_executable,
    )


def build_local_management_plane(
    layout: DirectoryLayout,
    *,
    base_service_environment: tuple[tuple[str, str], ...] = (),
    model_source_environment: tuple[tuple[str, str], ...] = (),
    huggingface_cli: str = "hf",
    model_storage_pools: Mapping[str, Path] | None = None,
    task_group: TaskGroupPort,
    docker_task_group: TaskGroupPort,
) -> ManagementPlaneAuthorities:
    local_commands = build_local_command_runner(task_group)
    docker_commands = build_local_command_runner(docker_task_group)
    gpu_runtime = NvidiaSmiGpuRuntimeObserver(LocalCommandResourceProbe(local_commands))
    host_runtime = LocalHostRuntimeObserver()
    directories = build_local_directory_authorities(layout)
    directory_layout = directories.layout
    meta = build_platform_meta(
        directory_layout.layout.state / "platform-meta",
        gpu_runtime_observer=gpu_runtime,
        host_runtime_observer=host_runtime,
    )
    docker_authority_id = canonical_digest(
        {
            "schema": "noetrium.docker-container-authority.v1",
            "state_root": str(directory_layout.layout.state.resolve()),
        }
    )
    docker_owner_generation_id = canonical_digest(
        {
            "schema": "noetrium.docker-controller-generation.v1",
            "authority_id": docker_authority_id,
            "nonce": uuid4().hex,
        }
    )
    docker_containers = DockerContainerLeaseAuthority(
        ownership=meta.resource_ownership,
        leases=meta.resource_leases,
        runtime=DockerCliManagedContainerProvider(
            docker_commands,
            authority_id=docker_authority_id,
        ),
        authority_id=docker_authority_id,
        owner_generation_id=docker_owner_generation_id,
        reconcile_on_start=False,
    )
    try:
        discovered_host = discover_local_compute_host(
            gpu_runtime_observer=gpu_runtime,
        )
    except RuntimeError:
        discovered_host = None
    if discovered_host is not None:
        meta.compute_inventory.register_host(discovered_host)
    scopes = meta.scopes
    host = compose_local_host(planner=meta.capability_composition)
    runner = SubprocessEnvironmentCommandRunner(local_commands)
    pip_cache = directory_layout.layout.cache / "pip"
    conda_cache = directory_layout.layout.cache / "conda-packages"
    environments = build_python_environment_authorities(
        directory_layout,
        (
            VenvEnvironmentBackend(runner, pip_cache=pip_cache),
            CondaEnvironmentBackend(
                runner, executable="conda", backend_id="conda",
                conda_package_cache=conda_cache, pip_cache=pip_cache,
            ),
            CondaEnvironmentBackend(
                runner, executable="mamba", backend_id="mamba",
                conda_package_cache=conda_cache, pip_cache=pip_cache,
            ),
        ),
        runner,
    )
    execution_environments = meta.environments
    asset_registry = ModelAssetRegistry(directory_layout)
    deployment_registry = ModelDeploymentRegistry(directory_layout)
    applied_store = AppliedModelDeploymentStore(directory_layout)
    # Exact clear tombstones dominate any active-path residue that can reappear
    # after a crash between unlink and directory durability. Converge those
    # paths before model controllers or new service starts are composed.
    applied_store.reconcile_cleared()
    asset_storage = LocalModelAssetStorage(directory_layout, additional_pools=model_storage_pools)
    deployment_catalog = ModelDeploymentCatalog(asset_registry, deployment_registry, environments.lifecycle)
    assets = ModelAssetManager(
        asset_registry,
        DeploymentModelAssetReferences(deployment_catalog),
        asset_storage,
        (HuggingFaceCliModelSource(
            asset_storage,
            executable=huggingface_cli,
            cache_root=directory_layout.layout.cache / "huggingface",
            environment=dict(model_source_environment),
            command_runner=local_commands,
        ),),
    )
    assignments = ModelAssignmentManager(scopes)
    service_factory = LocalModelServiceRuntimeFactory(
        directory_layout,
        operating_system=host.operating_system,
        task_group=task_group,
    )
    materializer = ModelLaunchMaterializer(
        assets, environments.lifecycle, base_environment=base_service_environment
    )
    deployment_runtime = ModelDeploymentRuntime(
        applied_store, deployment_catalog, materializer, service_factory
    )
    auto_recovery = DurableModelAutoRecoveryAuthority(directory_layout)
    fleet = ModelFleetRuntime(deployment_catalog, deployment_runtime, auto_recovery)
    deployment_logs = ModelDeploymentLogReader(
        applied_store, deployment_catalog, materializer, service_factory
    )
    resources = ModelResourceView(
        assets,
        deployment_catalog,
        fleet,
        gpu_runtime,
    )
    controller = ModelDesiredStateController(
        fleet,
        FileModelControllerStateStore(directory_layout.layout.state / "model" / "deployments" / "controller.json"),
    )
    models = ModelAuthorities(
        assets, assignments, deployment_catalog, deployment_runtime, fleet, deployment_logs, resources, controller
    )
    return ManagementPlaneAuthorities(
        scopes=scopes,
        directories=directories,
        execution_environments=execution_environments,
        python_environments=environments,
        models=models,
        model_revisions=sqlite_revision_authority(
            directory_layout.layout.state / "model" / "revisions.sqlite3"
        ),
        host=host,
        compute_scheduler=meta.compute_scheduler,
        deployment_qualification=build_local_deployment_qualification(
            directory_layout.layout.state / "model" / "qualification",
            environments.packages,
            environments.execution,
            local_commands,
            index_worker_path=QUALIFICATION_INDEX_WORKER_PATH,
        ),
        docker_containers=docker_containers,
        platform_meta=meta,
    )


def bind_local_model_replica_pool(
    plane: ManagementPlaneAuthorities,
    execution_pool: ResearchExecutionPool,
) -> LocalModelReplicaPoolRuntime:
    """Bind automatic local model placement to shared research resource authority."""

    if not isinstance(plane, ManagementPlaneAuthorities):
        raise TypeError("model replica pool requires ManagementPlaneAuthorities")
    if not isinstance(execution_pool, ResearchExecutionPool):
        raise TypeError("model replica pool requires ResearchExecutionPool")
    return LocalModelReplicaPoolRuntime(
        deployment_catalog=plane.models.deployment_catalog,
        deployment_runtime=plane.models.deployment_runtime,
        fleet=plane.models.fleet,
        compute_scheduler=plane.compute_scheduler,
        endpoint_allocations=plane.platform_meta.endpoint_allocations,
        compute_lease_guards=execution_pool.compute_lease_guard_factory(
            plane.compute_scheduler
        ),
        endpoint_lease_guards=execution_pool.endpoint_lease_guard_factory(
            plane.platform_meta.endpoint_allocations
        ),
    )


__all__ = [
    "LocalModelServiceRuntimeFactory",
    "ManagementPlaneAuthorities",
    "bind_local_model_replica_pool",
    "build_local_management_plane",
    "discover_local_docker_root",
]
