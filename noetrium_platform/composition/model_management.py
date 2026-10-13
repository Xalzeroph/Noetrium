from __future__ import annotations

from dataclasses import dataclass
import json
import os
from threading import RLock
from pathlib import Path
from typing import Mapping

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.foundation.kernel.kernel import canonical_digest, LocalLeaseClock
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_local_command_runner

from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayout, DirectoryLayoutPort, DirectoryManagementAuthorities, ManagedDirectoryKind
from noetrium_platform.infrastructure.resources.directory.composition import build_local_directory_authorities
from noetrium_platform.capabilities.model.api import ModelAuthorities, ModelRevisionAuthorityPort
from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentLogs, ModelDesiredDeployment
from noetrium_platform.capabilities.model.asset.providers import HuggingFaceCliModelSource
from noetrium_platform.capabilities.model.asset.runtime import LocalModelAssetStorage, ModelAssetManager, ModelAssetRegistry
from noetrium_platform.capabilities.model.composition import DeploymentModelAssetReferences
from noetrium_platform.capabilities.model.catalog.revision.composition import sqlite_revision_authority
from noetrium_platform.capabilities.model.deployment.composition import LocalModelReplicaPoolRuntime
from noetrium_platform.capabilities.model.assignment.runtime import ModelAssignmentManager
from noetrium_platform.capabilities.model.stack.runtime import (
    ModelArtifactClosureAuthority,
    ModelRuntimeAssetCache,
)
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
from noetrium_platform.infrastructure.resources.compute.providers import LocalHostRuntimeObserver, NvidiaSmiGpuRuntimeObserver
from noetrium_platform.composition.resource_probes import LocalCommandResourceProbe
from noetrium_platform.composition.model_qualification import QUALIFICATION_INDEX_WORKER_PATH
from noetrium_platform.infrastructure.lifecycle.python.api import PythonEnvironmentAuthorities
from noetrium_platform.capabilities.environment.catalog.api import ExecutionEnvironmentCatalogPort
from noetrium_platform.infrastructure.resources.container.providers import (
    DockerPhysicalProvider,
    discover_docker_root,
)
from noetrium_platform.infrastructure.resources.authority import (
    DEFAULT_AUTHORITY_LEASE_POLICY,
    UniversalResourceAuthority,
    binding_field,
    observation_field,
    physical_field,
)
from noetrium_platform.infrastructure.resources.container.api import (
    DockerCommandRunnerPort,
)
from noetrium_platform.foundation.scope.api import ScopeIndexPort
from noetrium_platform.infrastructure.lifecycle.python.runtime import (
    CondaEnvironmentBackend,
    build_python_environment_authorities,
    SubprocessEnvironmentCommandRunner,
    VenvEnvironmentBackend,
)
from noetrium_platform.infrastructure.lifecycle.service.api import (
    MaterializedServiceEnvironment,
    ServiceLaunchContract,
    ServiceProcessIdentity,
    ServiceQuiescenceOutcome,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime import (
    DirectoryCapturePathProvider,
    ExactServiceRuntimeEndpoint,
    HttpEndpointReadinessProbe,
    LocalServiceProcessAdapter,
    ProcessAliveReadinessProbe,
    ServiceExitClass,
    ServicePhase,
    StaticServiceEnvironmentProvider,
    ServiceStartIntent,
)
from noetrium_platform.composition.docker_service_process_backend import (
    DockerContainerProcessBackend,
    DockerServiceBindMount,
    DockerServiceProcessConfiguration,
    DockerServiceTmpfsMount,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_effect_journal import ServiceStartEffectJournal
from noetrium_platform.infrastructure.reliability.effect.runtime import sqlite_effect_intent_journal
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_transition import ServiceStateTransitionWriter

from noetrium_platform.infrastructure.lifecycle.service.composition import build_service_supervisor
from noetrium_platform.infrastructure.lifecycle.host.composition import HostComposition, compose_local_host
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.runtime_coordination import runtime_cache_root
from noetrium_platform.composition.platform_meta import (
    PlatformMetaAuthorities,
    build_platform_meta,
)
from noetrium_platform.infrastructure.resources.compute.composition import (
    discover_local_compute_host,
)
from noetrium_platform.infrastructure.resources.api import (
    resource_node,
    resource_topology,
)


_MODEL_SERVING_CACHE_ROOT = Path("/var/cache/noetrium/model-serving")
_MODEL_SERVING_CACHE_ENVIRONMENT = (
    ("TORCHINDUCTOR_CACHE_DIR", str(_MODEL_SERVING_CACHE_ROOT / "compile" / "torchinductor")),
    ("TRITON_CACHE_DIR", str(_MODEL_SERVING_CACHE_ROOT / "compile" / "triton")),
    ("CUDA_CACHE_PATH", str(_MODEL_SERVING_CACHE_ROOT / "compile" / "cuda")),
    ("VLLM_CACHE_ROOT", str(_MODEL_SERVING_CACHE_ROOT / "topology" / "vllm")),
)
_MODEL_COMPILE_DYNAMIC_VALUE_FLAGS = frozenset({
    "--host",
    "--port",
    "--data-parallel-rpc-port",
})
_MODEL_COMPILE_IGNORED_VALUE_FLAGS = frozenset({
    "--max-num-seqs",
    "--generation-config",
})
_MODEL_COMPILE_IGNORED_SWITCH_FLAGS = frozenset({
    "--disable-uvicorn-access-log",
    "--disable-log-stats",
    "--enable-server-load-tracking",
})


def _compile_semantic_compilation_config(raw: str) -> str | None:
    try:
        document = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return raw
    if not isinstance(document, dict):
        return raw
    # CUDA-graph capture buckets change startup work and runtime padding, not
    # the generated model graph. vLLM maintains its own internal graph-cache
    # hash under this outer cache, so stripping this field only enables safe
    # reuse of identical compiler artifacts.
    document.pop("cudagraph_capture_sizes", None)
    if not document:
        return None
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def _model_cache_semantic_argv(argv: tuple[str, ...]) -> tuple[str, ...]:
    rows: list[str] = []
    index = 0
    while index < len(argv):
        value = argv[index]
        if value in _MODEL_COMPILE_IGNORED_SWITCH_FLAGS:
            index += 1
            continue
        if value in _MODEL_COMPILE_DYNAMIC_VALUE_FLAGS:
            if index + 1 >= len(argv):
                rows.append(value)
                index += 1
                continue
            rows.extend((value, "<dynamic>"))
            index += 2
            continue
        if value in _MODEL_COMPILE_IGNORED_VALUE_FLAGS:
            index += 2 if index + 1 < len(argv) else 1
            continue
        if value == "--compilation-config":
            if index + 1 >= len(argv):
                rows.append(value)
                index += 1
                continue
            semantic = _compile_semantic_compilation_config(argv[index + 1])
            if semantic is not None:
                rows.extend((value, semantic))
            index += 2
            continue

        dynamic_match = next(
            (
                flag
                for flag in _MODEL_COMPILE_DYNAMIC_VALUE_FLAGS
                if value.startswith(flag + "=")
            ),
            None,
        )
        if dynamic_match is not None:
            rows.append(f"{dynamic_match}=<dynamic>")
            index += 1
            continue
        if any(
            value.startswith(flag + "=")
            for flag in _MODEL_COMPILE_IGNORED_VALUE_FLAGS
        ):
            index += 1
            continue
        compilation_prefix = "--compilation-config="
        if value.startswith(compilation_prefix):
            semantic = _compile_semantic_compilation_config(
                value[len(compilation_prefix):]
            )
            if semantic is not None:
                rows.append(compilation_prefix + semantic)
            index += 1
            continue
        rows.append(value)
        index += 1
    return tuple(rows)



def _model_serving_cache_keys(spec: ModelDesiredDeployment) -> tuple[str, str]:
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
            "schema": "noetrium.model-serving-topology-cache.v2",
            "compile_key": compile_key,
            # A one-device vLLM runtime has no inter-GPU topology state.
            # Sharing its vLLM graph cache across interchangeable placements
            # avoids recompiling the same stack whenever the scheduler moves
            # it to another GPU. Multi-GPU runtimes keep exact device tuples
            # because vLLM persists P2P topology evidence there.
            "gpu_topology": (
                ("single-device",)
                if len(spec.gpu_devices) == 1
                else spec.gpu_devices
            ),
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
    scopes: ScopeIndexPort
    directories: DirectoryManagementAuthorities
    durable_directories: DirectoryManagementAuthorities
    physical_directories: DirectoryManagementAuthorities
    execution_environments: ExecutionEnvironmentCatalogPort
    python_environments: PythonEnvironmentAuthorities
    models: ModelAuthorities
    model_revisions: ModelRevisionAuthorityPort
    host: HostComposition
    deployment_qualification: DeploymentQualificationAuthorities
    docker_provider: DockerPhysicalProvider
    platform_meta: PlatformMetaAuthorities


class LocalModelServiceRuntimeFactory:
    """Compose model serving through the single exact Service + Docker lifecycle."""

    def __init__(
        self,
        directories: DirectoryLayoutPort,
        *,
        assets: ModelAssetManager,
        runtime_asset_cache: ModelRuntimeAssetCache,
        resource_authority: UniversalResourceAuthority,
        docker_provider: DockerPhysicalProvider,
        docker_runner: DockerCommandRunnerPort,
        task_group: TaskGroupPort,
        base_environment: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self._directories = directories
        self._assets = assets
        if not isinstance(runtime_asset_cache, ModelRuntimeAssetCache):
            raise TypeError(
                "model service runtime requires ModelRuntimeAssetCache"
            )
        self._runtime_asset_cache = runtime_asset_cache
        self._resource_authority = resource_authority
        self._docker_provider = docker_provider
        self._docker_runner = docker_runner
        self._task_group = task_group
        self._base_environment = tuple(base_environment)
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
        spec: ModelDesiredDeployment,
        contract: ServiceLaunchContract,
    ) -> tuple[DockerServiceBindMount, ...]:
        asset = self._assets.model(spec.model_id)
        target_asset = Path(asset.path).expanduser().absolute()
        target_cwd = Path(contract.cwd).expanduser().absolute()
        rows: dict[str, DockerServiceBindMount] = {}

        authoritative_source = target_asset.resolve(strict=True)
        artifact_closure = ModelArtifactClosureAuthority().freeze(
            authoritative_source
        )
        runtime_source = self._runtime_asset_cache.resolve(
            authoritative_source,
            artifact_closure,
        )
        asset_mount = DockerServiceBindMount(
            runtime_source,
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

    def _service_state_store(
        self,
        contract: ServiceLaunchContract,
    ) -> FileServiceStateStore:
        service_key = self._safe(contract.service_id)
        return FileServiceStateStore(
            self._state_root
            / service_key
            / contract.digest()
            / "state.json"
        )

    def _service_effect_journal(
        self,
        contract: ServiceLaunchContract,
    ) -> ServiceStartEffectJournal:
        service_key = self._safe(contract.service_id)
        return ServiceStartEffectJournal(
            sqlite_effect_intent_journal(
                self._intent_root
                / service_key
                / contract.digest()
                / "effects.sqlite3"
            )
        )

    def _service_start_intents(
        self,
        service_id: str,
    ) -> tuple[ServiceStartIntent, ...]:
        if type(service_id) is not str or not service_id.strip():
            raise ValueError("model service recovery requires service_id")
        service_root = self._intent_root / self._safe(service_id)
        if not service_root.is_dir():
            return ()
        by_id: dict[str, ServiceStartIntent] = {}
        for contract_root in sorted(service_root.iterdir()):
            if not contract_root.is_dir():
                continue
            journal_path = contract_root / "effects.sqlite3"
            if not journal_path.exists():
                continue
            journal = ServiceStartEffectJournal(
                sqlite_effect_intent_journal(journal_path)
            )
            try:
                intents = journal.records_for_service(service_id)
            finally:
                journal.close()
            for intent in intents:
                contract = intent.contract
                if contract.service_id != service_id:
                    raise RuntimeError(
                        "model service-start history crossed service identity"
                    )
                if contract.digest() != contract_root.name:
                    raise RuntimeError(
                        "model service-start path crossed contract identity"
                    )
                current = by_id.get(intent.intent_id)
                if current is not None and current != intent:
                    raise RuntimeError(
                        "model service-start intent identity drifted: "
                        + intent.intent_id
                    )
                by_id[intent.intent_id] = intent
        return tuple(by_id[key] for key in sorted(by_id))

    def open(
        self,
        spec: ModelDesiredDeployment,
        contract: ServiceLaunchContract,
        *,
        environment: tuple[tuple[str, str], ...],
        readiness_url: str | None,
    ) -> ExactServiceRuntimeEndpoint:
        if type(spec) is not ModelDesiredDeployment:
            raise TypeError("model service runtime requires ModelDesiredDeployment")
        if spec.service_id != contract.service_id:
            raise ValueError("model service spec/contract service identity drifted")
        key = (canonical_digest(spec), contract.digest())

        with self._lock:
            existing = self._runtimes.get(key)
            if existing is not None:
                return existing[0]

            materialized = MaterializedServiceEnvironment(
                variables=environment,
                evidence_ref=f"model-serving-env:{contract.environment_digest}",
            )
            provider = StaticServiceEnvironmentProvider((materialized,))
            backend = DockerContainerProcessBackend(
                authority=self._resource_authority,
                provider=self._docker_provider,
                runner=self._docker_runner,
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
            state = self._service_state_store(contract)
            start_effects = self._service_effect_journal(contract)
            endpoint = ExactServiceRuntimeEndpoint(
                build_service_supervisor(state, start_effects, adapter)
            )
            self._runtimes[key] = (endpoint, backend)
            return endpoint

    def _environment_for_spec(
        self,
        spec: ModelDesiredDeployment,
    ) -> tuple[tuple[str, str], ...]:
        values = dict(self._base_environment)
        values.update(spec.environment)
        return tuple(sorted((str(key), str(value)) for key, value in values.items()))

    def frozen_contracts(
        self,
        spec: ModelDesiredDeployment,
    ) -> tuple[ServiceLaunchContract, ...]:
        """Recover immutable launch contracts only from causal service-start truth."""

        if type(spec) is not ModelDesiredDeployment:
            raise TypeError("model frozen contracts require ModelDesiredDeployment")
        by_digest: dict[str, ServiceLaunchContract] = {}
        for intent in self._service_start_intents(spec.service_id):
            contract = intent.contract
            digest = contract.digest()
            current = by_digest.get(digest)
            if current is not None and current != contract:
                raise RuntimeError(
                    "model service-start contract digest collision: " + digest
                )
            by_digest[digest] = contract
        return tuple(by_digest[key] for key in sorted(by_digest))

    def quiesce(
        self,
        spec: ModelDesiredDeployment,
        *,
        contracts: tuple[ServiceLaunchContract, ...],
    ) -> tuple[ServiceQuiescenceOutcome, ...]:
        if type(spec) is not ModelDesiredDeployment:
            raise TypeError("model service quiescence requires ModelDesiredDeployment")
        if type(contracts) is not tuple or any(
            not isinstance(contract, ServiceLaunchContract)
            for contract in contracts
        ):
            raise TypeError(
                "model service quiescence requires tuple[ServiceLaunchContract, ...]"
            )
        by_digest: dict[str, ServiceLaunchContract] = {}
        for contract in contracts:
            if contract.service_id != spec.service_id:
                raise RuntimeError(
                    "model frozen service contract belongs to another service: "
                    + contract.service_id
                )
            digest = contract.digest()
            current = by_digest.get(digest)
            if current is not None and current != contract:
                raise RuntimeError(
                    "model frozen service contract digest collision: " + digest
                )
            by_digest[digest] = contract
        environment = self._environment_for_spec(spec)
        outcomes: list[ServiceQuiescenceOutcome] = []
        for digest in sorted(by_digest):
            contract = by_digest[digest]
            endpoint = self.open(
                spec,
                contract,
                environment=environment,
                readiness_url=spec.readiness_url,
            )
            outcome = endpoint.quiesce_exact(contract)
            if not outcome.quiescent:
                raise RuntimeError(
                    "model service did not reach exact quiescence: "
                    + spec.deployment_id
                    + ": "
                    + outcome.summary
                )
            outcomes.append(outcome)
        return tuple(outcomes)

    @staticmethod
    def _docker_process_coordinates(process) -> tuple[str, str]:
        prefix = "docker:"
        start_identity = process.start_identity
        if not start_identity.startswith(prefix):
            raise RuntimeError(
                "model service retired process is not Docker-backed: "
                + start_identity
            )
        remainder = start_identity[len(prefix):]
        container_id, separator, started_at = remainder.partition(":")
        if (
            not separator
            or len(container_id) < 12
            or not started_at.strip()
        ):
            raise RuntimeError(
                "model service Docker process identity is malformed: "
                + start_identity
            )
        return container_id, started_at

    def quiesce_retired(
        self,
        deployment_id: str,
    ) -> tuple[ServiceQuiescenceOutcome, ...]:
        """Compensate retired model-service effects from causal Effect truth.

        Desired model configuration is intentionally not reconstructed here.
        A retired identity is allowed to drive only the inverse physical effect
        proven by its exact service-start record and current Resource binding.
        """

        if type(deployment_id) is not str or not deployment_id.strip():
            raise ValueError("retired model recovery requires deployment_id")
        service_id = "model:" + deployment_id.strip()
        intents = self._service_start_intents(service_id)
        outcomes: list[ServiceQuiescenceOutcome] = []
        for intent in intents:
            contract = intent.contract
            state_store = self._service_state_store(contract)
            state = state_store.read() if state_store.exists() else None
            process = intent.process
            if process is None:
                if state is not None and state.process is not None:
                    raise RuntimeError(
                        "service state contains process absent from Effect truth: "
                        + deployment_id
                    )
                outcomes.append(
                    ServiceQuiescenceOutcome(
                        contract.digest(),
                        True,
                        "retired service effect has no physical process",
                    )
                )
                continue

            container_id, started_at = self._docker_process_coordinates(process)
            binding = self._resource_authority.binding_for_physical(
                "docker",
                container_id,
            )
            if binding is None:
                already_quiescent = (
                    state is not None
                    and state.phase is ServicePhase.EXITED
                    and state.process is None
                )
                outcomes.append(
                    ServiceQuiescenceOutcome(
                        contract.digest(),
                        already_quiescent,
                        (
                            "retired service effect already quiescent"
                            if already_quiescent
                            else (
                                "retired service effect has no current Resource "
                                "binding; physical absence remains unproven"
                            )
                        ),
                    )
                )
                continue

            physical = binding_field(binding, "physical_identity")
            attributes = dict(physical_field(physical, "attributes") or {})
            if (
                physical_field(physical, "provider_kind") != "docker"
                or physical_field(physical, "physical_id") != container_id
                or attributes.get("pid") != process.pid
                or attributes.get("started_at") != started_at
            ):
                raise RuntimeError(
                    "retired service Effect identity disagrees with Resource binding: "
                    + deployment_id
                )
            if (
                state is not None
                and state.process is not None
                and state.process != process
            ):
                raise RuntimeError(
                    "retired service state process disagrees with Effect truth: "
                    + deployment_id
                )

            resource_key = str(binding_field(binding, "resource_key"))
            topology = resource_topology(
                "retired-service:"
                + canonical_digest(
                    {
                        "deployment_id": deployment_id,
                        "contract_digest": contract.digest(),
                        "resource_key": resource_key,
                    }
                )[:24],
                resources=(
                    resource_node(
                        "container",
                        kind="container",
                        authority_key=resource_key,
                        realization=True,
                    ),
                ),
            )
            self._resource_authority.reconcile(
                topology,
                claim_candidates={},
                realization_specs={},
                providers={"docker": self._docker_provider},
                desired_resource_ids=frozenset(),
            )
            if self._resource_authority.binding_for_physical(
                "docker", container_id
            ) is not None:
                raise RuntimeError(
                    "retired Docker binding survived Authority reconciliation: "
                    + deployment_id
                )
            observed = self._docker_provider.observe(physical)
            if observation_field(observed, "exists"):
                raise RuntimeError(
                    "retired Docker physical process survived reconciliation: "
                    + deployment_id
                )

            transitions = ServiceStateTransitionWriter(state_store)
            if state is None:
                state = transitions.initialize(contract)
            state = transitions.persist(
                state,
                ServicePhase.EXITED,
                process=None,
                last_exit_class=ServiceExitClass.CLEAN,
            )
            verified = state_store.read()
            if verified.phase is not ServicePhase.EXITED or verified.process is not None:
                raise RuntimeError(
                    "retired service state did not converge to EXITED: "
                    + deployment_id
                )
            outcomes.append(
                ServiceQuiescenceOutcome(
                    contract.digest(),
                    True,
                    "retired service physical effect compensated",
                    (
                        "docker-container:" + container_id,
                        "resource-binding:" + resource_key,
                    ),
                )
            )
        return tuple(outcomes)

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
    durable_layout: DirectoryLayout | None = None,
    physical_layout: DirectoryLayout | None = None,
    base_service_environment: tuple[tuple[str, str], ...] = (),
    model_source_environment: tuple[tuple[str, str], ...] = (),
    huggingface_cli: str = "hf",
    model_storage_pools: Mapping[str, Path] | None = None,
    task_group: TaskGroupPort,
    docker_task_group: TaskGroupPort,
    execution_pool: ResearchExecutionPool,
    resource_authority: UniversalResourceAuthority,
) -> ManagementPlaneAuthorities:
    if not isinstance(execution_pool, ResearchExecutionPool):
        raise TypeError("management plane requires ResearchExecutionPool")
    if not isinstance(resource_authority, UniversalResourceAuthority):
        raise TypeError(
            "management plane requires the sole UniversalResourceAuthority"
        )
    local_commands = build_local_command_runner(task_group)
    docker_commands = build_local_command_runner(docker_task_group)
    gpu_runtime = NvidiaSmiGpuRuntimeObserver(LocalCommandResourceProbe(local_commands))
    # Inventory and live-pressure observation must share the same physical host
    # identity. Container hostnames are process-local implementation detail and
    # cannot be used as the compute authority key.
    lease_clock = LocalLeaseClock()
    physical_host_identity = lease_clock.read().host_identity_digest
    host_runtime = LocalHostRuntimeObserver(host_id=physical_host_identity)
    directories = build_local_directory_authorities(layout, resource_authority)
    directory_layout = directories.layout
    durable_directories = (
        directories
        if durable_layout is None
        else build_local_directory_authorities(
            durable_layout, resource_authority
        )
    )
    durable_directory_layout = durable_directories.layout
    physical_directories = (
        directories
        if physical_layout is None
        else build_local_directory_authorities(
            physical_layout, resource_authority
        )
    )
    physical_directory_layout = physical_directories.layout
    meta = build_platform_meta(
        directory_layout.layout.state / "platform-meta",
        resource_authority=resource_authority,
        artifact_root=durable_directory_layout.layout.state / "platform-meta",
        gpu_runtime_observer=gpu_runtime,
        host_runtime_observer=host_runtime,
    )
    docker_provider = DockerPhysicalProvider(docker_commands)
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
    pip_cache = durable_directory_layout.layout.cache / "pip"
    conda_cache = durable_directory_layout.layout.cache / "conda-packages"
    environments = build_python_environment_authorities(
        durable_directory_layout,
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
        meta.resource_authority,
    )
    execution_environments = meta.environments
    asset_registry = ModelAssetRegistry(durable_directory_layout)
    deployment_registry = ModelDeploymentRegistry(physical_directory_layout)
    applied_store = AppliedModelDeploymentStore(physical_directory_layout)
    asset_storage = LocalModelAssetStorage(
        durable_directory_layout,
        additional_pools=model_storage_pools,
    )
    deployment_catalog = ModelDeploymentCatalog(asset_registry, deployment_registry)
    external_huggingface_cache_raw = os.environ.get(
        "NOETRIUM_HUGGINGFACE_CACHE_ROOT", ""
    ).strip()
    external_huggingface_cache = None
    if external_huggingface_cache_raw:
        external_huggingface_cache = Path(external_huggingface_cache_raw)
        if not external_huggingface_cache.is_absolute():
            raise ValueError(
                "NOETRIUM_HUGGINGFACE_CACHE_ROOT must be an absolute path"
            )
    assets = ModelAssetManager(
        asset_registry,
        DeploymentModelAssetReferences(deployment_catalog),
        asset_storage,
        (HuggingFaceCliModelSource(
            asset_storage,
            executable=huggingface_cli,
            cache_root=durable_directory_layout.layout.cache / "huggingface",
            external_cache_root=external_huggingface_cache,
            environment=dict(model_source_environment),
            command_runner=local_commands,
        ),),
    )
    assignments = ModelAssignmentManager(scopes)
    serving_environment = _model_serving_environment(base_service_environment)
    runtime_asset_cache = ModelRuntimeAssetCache(
        runtime_cache_root() / "model-assets"
    )
    service_factory = LocalModelServiceRuntimeFactory(
        physical_directory_layout,
        assets=assets,
        runtime_asset_cache=runtime_asset_cache,
        resource_authority=meta.resource_authority,
        docker_provider=docker_provider,
        docker_runner=docker_commands,
        task_group=task_group,
        base_environment=serving_environment,
    )
    execution_pool.register_lifecycle_resource(service_factory)
    materializer = ModelLaunchMaterializer(
        assets,
        gpu_runtime_observer=gpu_runtime,
        base_environment=serving_environment,
    )
    deployment_runtime = ModelDeploymentRuntime(
        applied_store, deployment_catalog, materializer, service_factory
    )
    auto_recovery = DurableModelAutoRecoveryAuthority(physical_directory_layout)
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
        FileModelControllerStateStore(physical_directory_layout.layout.state / "model" / "deployments" / "controller.json"),
    )
    models = ModelAuthorities(
        assets, assignments, deployment_catalog, deployment_runtime, fleet, deployment_logs, resources, controller
    )
    return ManagementPlaneAuthorities(
        scopes=scopes,
        directories=directories,
        durable_directories=durable_directories,
        physical_directories=physical_directories,
        execution_environments=execution_environments,
        python_environments=environments,
        models=models,
        model_revisions=sqlite_revision_authority(
            durable_directory_layout.layout.state / "model" / "revisions.sqlite3"
        ),
        host=host,
        deployment_qualification=build_local_deployment_qualification(
            durable_directory_layout.layout.state / "model" / "qualification",
            environments.packages,
            environments.execution,
            local_commands,
            index_worker_path=QUALIFICATION_INDEX_WORKER_PATH,
        ),
        docker_provider=docker_provider,
        platform_meta=meta,
    )


def bind_local_model_replica_pool(
    plane: ManagementPlaneAuthorities,
    execution_pool: ResearchExecutionPool,
) -> LocalModelReplicaPoolRuntime:
    """Bind model placement directly to the sole Universal Resource Authority."""

    if not isinstance(plane, ManagementPlaneAuthorities):
        raise TypeError("model replica pool requires ManagementPlaneAuthorities")
    if not isinstance(execution_pool, ResearchExecutionPool):
        raise TypeError("model replica pool requires ResearchExecutionPool")
    meta = plane.platform_meta
    return LocalModelReplicaPoolRuntime(
        deployment_catalog=plane.models.deployment_catalog,
        deployment_runtime=plane.models.deployment_runtime,
        resource_authority=meta.resource_authority,
        compute_inventory=meta.compute_inventory,
        endpoint_candidates=meta.endpoint_candidates,
        endpoint_probe=meta.endpoint_probe,
        gpu_runtime_observer=meta.gpu_runtime_observer,
        host_runtime_observer=meta.host_runtime_observer,
        runtime_fabric_resource_key="runtime-fabric:host-runtime-fabric",
        runtime_fabric_consumer_lease_id=(
            "runtime-fabric-consumer:" + execution_pool.owner_generation_id
        ),
        consumer_lease_guard_factory=execution_pool.resource_lease_guard_factory(
            meta.resource_authority
        ),
        consumer_lease_policy=DEFAULT_AUTHORITY_LEASE_POLICY,
        consumer_holder_id=execution_pool.owner_generation_id,
    )


__all__ = [
    "LocalModelServiceRuntimeFactory",
    "ManagementPlaneAuthorities",
    "bind_local_model_replica_pool",
    "build_local_management_plane",
    "discover_local_docker_root",
]
