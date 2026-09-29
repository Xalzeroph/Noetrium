from __future__ import annotations

from dataclasses import dataclass
import os
from threading import RLock
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_local_command_runner

from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayout, DirectoryLayoutPort, DirectoryManagementAuthorities
from noetrium_platform.infrastructure.resources.directory.runtime import build_local_directory_authorities
from noetrium_platform.capabilities.model.api import ModelAuthorities, ModelRevisionAuthorityPort
from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentLogs, ModelDeploymentSpec
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
from noetrium_platform.infrastructure.resources.container.api import (
    DockerCommandRunnerPort,
    DockerContainerLeaseGuardFactoryPort,
)
from noetrium_platform.infrastructure.resources.container.runtime import (
    DockerContainerLeaseAuthority,
)
from noetrium_platform.infrastructure.resources.lease.runtime import LocalLeaseClock
from noetrium_platform.foundation.scope.api import ScopeRegistryPort
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
from noetrium_platform.composition.docker_service_process_backend import (
    DockerContainerProcessBackend,
    DockerServiceBindMount,
    DockerServiceProcessConfiguration,
    DockerServiceTmpfsMount,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_intent_store import DirectoryServiceStartIntentStore
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore

from noetrium_platform.infrastructure.lifecycle.service.composition import build_service_supervisor
from noetrium_platform.infrastructure.lifecycle.host.composition import HostComposition, compose_local_host
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.platform_meta import (
    PlatformMetaAuthorities,
    build_platform_meta,
)
from noetrium_platform.infrastructure.resources.compute.composition import (
    discover_local_compute_host,
)


_MODEL_SERVING_CACHE_ROOT = Path("/var/cache/noetrium/model-serving")
_MODEL_SERVING_CACHE_ENVIRONMENT = (
    ("TORCHINDUCTOR_CACHE_DIR", str(_MODEL_SERVING_CACHE_ROOT / "compile" / "torchinductor")),
    ("TRITON_CACHE_DIR", str(_MODEL_SERVING_CACHE_ROOT / "compile" / "triton")),
    ("CUDA_CACHE_PATH", str(_MODEL_SERVING_CACHE_ROOT / "compile" / "cuda")),
    ("VLLM_CACHE_ROOT", str(_MODEL_SERVING_CACHE_ROOT / "topology" / "vllm")),
)
_DYNAMIC_MODEL_ENDPOINT_FLAGS = frozenset({
    "--host",
    "--port",
    "--data-parallel-rpc-port",
})


def _model_cache_semantic_argv(argv: tuple[str, ...]) -> tuple[str, ...]:
    rows: list[str] = []
    index = 0
    while index < len(argv):
        value = argv[index]
        if value in _DYNAMIC_MODEL_ENDPOINT_FLAGS:
            rows.extend((value, "<dynamic>"))
            index += 2
            continue
        matched = next(
            (flag for flag in _DYNAMIC_MODEL_ENDPOINT_FLAGS if value.startswith(flag + "=")),
            None,
        )
        rows.append(f"{matched}=<dynamic>" if matched is not None else value)
        index += 1
    return tuple(rows)


def _model_serving_cache_keys(spec: ModelDeploymentSpec) -> tuple[str, str]:
    compile_key = canonical_digest(
        {
            "schema": "noetrium.model-serving-compile-cache.v1",
            "model_id": spec.model_id,
            "engine": spec.engine,
            "container_digest": spec.container_digest,
            "executable": spec.executable,
            "argv": _model_cache_semantic_argv(spec.argv),
            "environment": spec.environment,
        }
    )
    topology_key = canonical_digest(
        {
            "schema": "noetrium.model-serving-topology-cache.v1",
            "compile_key": compile_key,
            "gpu_devices": spec.gpu_devices,
        }
    )
    return compile_key, topology_key


def _model_serving_environment(
    base_environment: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    resolved = dict(base_environment)
    for key, value in _MODEL_SERVING_CACHE_ENVIRONMENT:
        existing = resolved.get(key)
        if existing is not None and existing != value:
            raise ValueError(
                f"model serving cache environment is platform-owned: {key}"
            )
        resolved[key] = value
    return tuple(sorted(resolved.items()))


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
    """Compose model serving through the single exact Service + Docker lifecycle."""

    def __init__(
        self,
        directories: DirectoryLayoutPort,
        *,
        assets: ModelAssetManager,
        docker_containers: DockerContainerLeaseAuthority,
        docker_runner: DockerCommandRunnerPort,
        docker_lease_guards: DockerContainerLeaseGuardFactoryPort,
        task_group: TaskGroupPort,
    ) -> None:
        self._directories = directories
        self._assets = assets
        self._docker_containers = docker_containers
        self._docker_runner = docker_runner
        self._docker_lease_guards = docker_lease_guards
        self._task_group = task_group
        self._state_root = directories.layout.state / "model-services"
        self._intent_root = directories.layout.runtime / "model-service-start-intents"
        self._capture_root = directories.layout.logs / "model-services"
        self._lock = RLock()
        self._runtimes: dict[
            tuple[str, str],
            tuple[ExactServiceRuntimeEndpoint, DockerContainerProcessBackend],
        ] = {}

    def _mounts(
        self,
        spec: ModelDeploymentSpec,
        contract: ServiceLaunchContract,
    ) -> tuple[DockerServiceBindMount, ...]:
        asset = self._assets.model(spec.model_id)
        target_asset = Path(asset.path).expanduser().absolute()
        target_cwd = Path(contract.cwd).expanduser().absolute()
        rows: dict[str, DockerServiceBindMount] = {}

        asset_mount = DockerServiceBindMount(
            target_asset.resolve(strict=True),
            target_asset,
            read_only=True,
        )
        rows[str(asset_mount.target)] = asset_mount

        cwd_mount = DockerServiceBindMount(
            target_cwd.resolve(strict=True),
            target_cwd,
            read_only=True,
        )
        rows.setdefault(str(cwd_mount.target), cwd_mount)

        compile_key, topology_key = _model_serving_cache_keys(spec)
        cache_root = self._directories.layout.cache / "model-serving"
        cache_mounts = (
            (
                cache_root / "compile" / compile_key,
                _MODEL_SERVING_CACHE_ROOT / "compile",
            ),
            (
                cache_root / "topology" / topology_key,
                _MODEL_SERVING_CACHE_ROOT / "topology",
            ),
        )
        for source, target in cache_mounts:
            source.mkdir(parents=True, exist_ok=True)
            mount = DockerServiceBindMount(source, target, read_only=False)
            rows[str(mount.target)] = mount
        return tuple(rows[key] for key in sorted(rows))

    def open(
        self,
        spec: ModelDeploymentSpec,
        contract: ServiceLaunchContract,
        *,
        environment: tuple[tuple[str, str], ...],
        readiness_url: str | None,
    ) -> ExactServiceRuntimeEndpoint:
        if type(spec) is not ModelDeploymentSpec:
            raise TypeError("model service runtime requires ModelDeploymentSpec")
        if spec.service_id != contract.service_id:
            raise ValueError("model service spec/contract service identity drifted")
        key = (canonical_digest(spec), contract.digest())

        with self._lock:
            existing = self._runtimes.get(key)
            if existing is not None:
                return existing[0]

            service_key = self._safe(contract.service_id)
            materialized = MaterializedServiceEnvironment(
                variables=environment,
                evidence_ref=f"model-serving-env:{contract.environment_digest}",
            )
            provider = StaticServiceEnvironmentProvider((materialized,))
            backend = DockerContainerProcessBackend(
                authority=self._docker_containers,
                runner=self._docker_runner,
                lease_guard_factory=self._docker_lease_guards,
                configuration=DockerServiceProcessConfiguration(
                    image_digest=spec.container_digest,
                    holder_scope=spec.scope,
                    mounts=self._mounts(spec, contract),
                    tmpfs_mounts=(
                        DockerServiceTmpfsMount(
                            Path("/tmp"),
                            4 * 1024 ** 3,
                            executable=True,
                        ),
                    ),
                    gpu_devices=spec.gpu_devices,
                    network_host=True,
                    ipc_host=True,
                    user_uid=os.getuid(),
                    user_gid=os.getgid(),
                ),
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
            state = FileServiceStateStore(
                self._state_root / service_key / contract_key / "state.json"
            )
            intents = DirectoryServiceStartIntentStore(
                self._intent_root / service_key / contract_key
            )
            endpoint = ExactServiceRuntimeEndpoint(
                build_service_supervisor(state, intents, adapter)
            )
            self._runtimes[key] = (endpoint, backend)
            return endpoint

    def logs(
        self,
        contract: ServiceLaunchContract,
        *,
        deployment_id: str,
    ) -> ModelDeploymentLogs:
        paths = DirectoryCapturePathProvider(self._capture_root).paths(contract)
        return ModelDeploymentLogs(
            deployment_id,
            paths.stdout_path,
            paths.stderr_path,
        )

    def close(self) -> None:
        with self._lock:
            rows = tuple(reversed(tuple(self._runtimes.values())))
            self._runtimes.clear()
        errors: list[BaseException] = []
        for _endpoint, backend in rows:
            try:
                backend.close()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise BaseExceptionGroup(
                "model Docker service heartbeat shutdown failed",
                errors,
            )

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
    execution_pool: ResearchExecutionPool,
) -> ManagementPlaneAuthorities:
    if not isinstance(execution_pool, ResearchExecutionPool):
        raise TypeError("management plane requires ResearchExecutionPool")
    local_commands = build_local_command_runner(task_group)
    docker_commands = build_local_command_runner(docker_task_group)
    gpu_runtime = NvidiaSmiGpuRuntimeObserver(LocalCommandResourceProbe(local_commands))
    host_runtime = LocalHostRuntimeObserver()
    directories = build_local_directory_authorities(layout)
    directory_layout = directories.layout
    lease_clock = LocalLeaseClock()
    physical_host_identity = lease_clock.read().host_identity_digest
    meta = build_platform_meta(
        directory_layout.layout.state / "platform-meta",
        gpu_runtime_observer=gpu_runtime,
        host_runtime_observer=host_runtime,
        lease_clock=lease_clock,
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
            # Docker observation/recovery may be called synchronously from an
            # orchestration ASYNC_IO task (for example service readiness).
            # Keeping Docker control commands in the independent control-plane
            # task group prevents the event loop from synchronously waiting on
            # a child task submitted back to itself.
            docker_commands,
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
            host_id=physical_host_identity,
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
    deployment_catalog = ModelDeploymentCatalog(asset_registry, deployment_registry)
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
        assets=assets,
        docker_containers=docker_containers,
        docker_runner=docker_commands,
        docker_lease_guards=execution_pool.docker_container_lease_guard_factory(
            docker_containers
        ),
        task_group=task_group,
    )
    execution_pool.register_model_lifecycle_resource(service_factory)
    materializer = ModelLaunchMaterializer(
        assets,
        gpu_runtime_observer=gpu_runtime,
        base_environment=_model_serving_environment(base_service_environment),
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
