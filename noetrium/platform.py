"""Stable product facade for applications built on Noetrium."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from noetrium_platform.api import (
    ProjectTestStage,
    ProjectTestStageReceipt,
    ResearchAction,
    ResearchApplicationPort,
    ResearchFacade,
    ResearchOperationFailure,
    ResearchRequest,
    ResearchResult,
)
from noetrium_platform.capabilities.environment.api import (
    EnvironmentCapability,
    EnvironmentIdentity,
    EnvironmentProviderCapabilities,
    EnvironmentSession,
    EnvironmentSessionServices,
)
from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftAgentSpec,
    MinecraftBridgeSpec,
    MinecraftEndpointSpec,
    MinecraftEnvironmentSpec,
)
from noetrium_platform.capabilities.environment.minecraft.composition.environment import (
    compose_minecraft_environment,
)
from noetrium_platform.capabilities.model.api import (
    ModelBindingDiagnostic,
    ModelCapabilityRequirement,
    ModelProviderProfile,
    ProjectModelClientPort,
    ProjectModelProviderPort,
)
from noetrium_platform.capabilities.model.providers import QualifiedModelProjectProvider
from noetrium_platform.capabilities.model.request.api import ModelRequestRecorderPort
from noetrium_platform.capabilities.model.request.composition.recorder import (
    build_directory_model_request_recorder,
)
from noetrium_platform.capabilities.model.serving.endpoint.composition import (
    build_openai_compatible_qualified_endpoint,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    PersistedQualifiedModelEndpointBinding,
    load_qualified_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.providers import (
    DirectoryRuntimeCanaryEvidenceStore,
    DirectoryRuntimeQualificationEvidenceStore,
)
from noetrium_platform.capabilities.model.serving.runtime.admission import (
    ModelAdmissionRegistry,
)
from noetrium_platform.foundation.kernel.concurrency.composition import (
    build_concurrency_runtime,
)
from noetrium_platform.infrastructure.lifecycle.host.providers import (
    LocalOperatingSystemRoute,
)
from noetrium_platform.product.operator.runtime.run_control_application import (
    bind_run_control_application,
)
from noetrium_platform.research.experimentation.run.api import RunArtifactStorePort
from noetrium_platform.research.experimentation.run.composition.artifacts import (
    build_directory_run_artifact_store,
)


class MinecraftEnvironmentBinding:
    """Owned public binding for one Minecraft environment provider.

    The binding is deliberately small: downstream projects receive the public
    EnvironmentProviderPort shape while Noetrium retains ownership of provider
    composition, host routing, structured concurrency and session cleanup.
    """

    def __init__(
        self,
        spec: MinecraftEnvironmentSpec,
        *,
        task_group_id: str = "project:minecraft",
    ) -> None:
        if not task_group_id.strip():
            raise ValueError("task_group_id must be non-empty")
        self._spec = spec
        self._concurrency = build_concurrency_runtime(
            blocking_io_thread_name_prefix="minecraft-project-binding",
            timer_name="minecraft-project-binding-timer",
        )
        try:
            self._task_group = self._concurrency.open_task_group(task_group_id)
            self._assembly = compose_minecraft_environment(
                spec,
                operating_system=LocalOperatingSystemRoute(),
                task_group=self._task_group,
            )
        except BaseException:
            self._concurrency.close()
            raise
        self._sessions: list[EnvironmentSession] = []
        self._closed = False

    @property
    def spec(self) -> MinecraftEnvironmentSpec:
        return self._spec

    @property
    def identity(self) -> EnvironmentIdentity:
        return self._assembly.implementation.identity

    @property
    def capabilities(self) -> EnvironmentProviderCapabilities:
        supported = [
            EnvironmentCapability.RECONCILE,
            EnvironmentCapability.DIAGNOSTICS,
            EnvironmentCapability.QUERY,
        ]
        if self._assembly.implementation.checkpoint is not None:
            supported.extend(
                (EnvironmentCapability.SNAPSHOT, EnvironmentCapability.RESTORE)
            )
        return EnvironmentProviderCapabilities(tuple(supported))

    def open_session(
        self,
        *,
        session_id: str,
        services: EnvironmentSessionServices,
    ) -> EnvironmentSession:
        if self._closed:
            raise RuntimeError("Minecraft environment binding is closed")
        session = self._assembly.runtime.open_session(
            self._assembly.implementation,
            session_id=session_id,
            services=services,
        )
        self._sessions.append(session)
        return session

    def close(self) -> None:
        if self._closed:
            return
        first_error: BaseException | None = None
        for session in reversed(self._sessions):
            try:
                session.close()
            except BaseException as exc:  # cleanup must continue across sessions
                if first_error is None:
                    first_error = exc
        self._sessions.clear()
        try:
            self._concurrency.close()
        except BaseException as exc:
            if first_error is None:
                first_error = exc
        self._closed = True
        if first_error is not None:
            raise RuntimeError("Minecraft environment binding cleanup failed") from first_error

    def __enter__(self) -> "MinecraftEnvironmentBinding":
        if self._closed:
            raise RuntimeError("Minecraft environment binding is closed")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


def bind_minecraft_environment(
    spec: MinecraftEnvironmentSpec,
    *,
    task_group_id: str = "project:minecraft",
) -> MinecraftEnvironmentBinding:
    """Bind an explicit Minecraft spec through the stable product facade."""

    if not isinstance(spec, MinecraftEnvironmentSpec):
        raise TypeError("spec must be MinecraftEnvironmentSpec")
    return MinecraftEnvironmentBinding(spec, task_group_id=task_group_id)


def bind_bundled_minecraft_environment(
    *,
    host: str = "127.0.0.1",
    port: int = 25565,
    username: str = "ResearchBot",
    auth: str = "offline",
    version: str = "",
    node_executable: str = "node",
    action_recovery_root: str | None = None,
    connect_timeout_s: float = 45.0,
    command_timeout_s: float = 45.0,
    task_group_id: str = "project:minecraft",
) -> MinecraftEnvironmentBinding:
    """Bind the packaged Mineflayer bridge without exposing private asset paths."""

    if not node_executable.strip():
        raise ValueError("node_executable must be non-empty")
    bridge_root = resources.files(
        "noetrium_platform.capabilities.environment.minecraft.providers"
    ).joinpath("assets", "mineflayer_bridge")
    bridge_script = bridge_root.joinpath("bridge.js")
    spec = MinecraftEnvironmentSpec(
        endpoint=MinecraftEndpointSpec(host=host, port=port),
        bridge=MinecraftBridgeSpec(
            command=(node_executable, str(bridge_script)),
            cwd=str(bridge_root),
            action_recovery_root=action_recovery_root,
            connect_timeout_s=connect_timeout_s,
            command_timeout_s=command_timeout_s,
        ),
        agent=MinecraftAgentSpec(
            username=username,
            auth=auth,
            version=version,
        ),
    )
    return bind_minecraft_environment(spec, task_group_id=task_group_id)


class QualifiedProjectModelBinding:
    """Owned project binding over an already-qualified model deployment closure.

    Qualification evidence and deployment identity stay authoritative in the
    persisted Noetrium closure. The product facade owns endpoint materialization,
    request provenance storage, admission control and structured concurrency so
    downstream projects never need to import those implementation modules.
    """

    def __init__(
        self,
        profile: ModelProviderProfile,
        *,
        closure_path: str | Path,
        request_root: str | Path,
        api_key: str = "",
        timeout_s: float | None = None,
        task_group_id: str = "project:model",
    ) -> None:
        if not isinstance(profile, ModelProviderProfile):
            raise TypeError("profile must be ModelProviderProfile")
        if not task_group_id.strip():
            raise ValueError("task_group_id must be non-empty")
        if timeout_s is not None and timeout_s <= 0:
            raise ValueError("timeout_s must be positive when provided")
        self._profile = profile
        self._concurrency = build_concurrency_runtime(
            blocking_io_thread_name_prefix="model-project-binding",
            timer_name="model-project-binding-timer",
        )
        self._admission = ModelAdmissionRegistry()
        try:
            self._task_group = self._concurrency.open_task_group(task_group_id)
            closure = load_qualified_model_deployment_closure(
                closure_path,
                runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
                runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
            )
            bindings = PersistedQualifiedModelEndpointBinding(closure)
            self._model_requests = build_directory_model_request_recorder(
                Path(request_root).expanduser().resolve(strict=False)
            )

            def endpoint_factory(binding):
                return build_openai_compatible_qualified_endpoint(
                    binding,
                    api_key=api_key,
                    timeout_s=timeout_s,
                    task_group=self._task_group,
                    admission_registry=self._admission,
                )

            self._provider: ProjectModelProviderPort = QualifiedModelProjectProvider(
                profile,
                bindings,
                endpoint_factory,
                self._model_requests,
            )
        except BaseException:
            self._admission.close()
            self._concurrency.close()
            raise
        self._closed = False

    @property
    def profile(self) -> ModelProviderProfile:
        return self._profile

    @property
    def provider(self) -> ProjectModelProviderPort:
        return self._provider

    @property
    def model_requests(self) -> ModelRequestRecorderPort:
        return self._model_requests

    def bind(self, requirement: ModelCapabilityRequirement) -> ProjectModelClientPort:
        if self._closed:
            raise RuntimeError("qualified project model binding is closed")
        return self._provider.bind(requirement)

    def diagnose(
        self,
        requirement: ModelCapabilityRequirement,
    ) -> tuple[ModelBindingDiagnostic, ...]:
        if self._closed:
            raise RuntimeError("qualified project model binding is closed")
        return self._provider.diagnose(requirement)

    def close(self) -> None:
        if self._closed:
            return
        first_error: BaseException | None = None
        try:
            self._admission.close()
        except BaseException as exc:
            first_error = exc
        try:
            self._concurrency.close()
        except BaseException as exc:
            if first_error is None:
                first_error = exc
        self._closed = True
        if first_error is not None:
            raise RuntimeError("qualified project model binding cleanup failed") from first_error

    def __enter__(self) -> "QualifiedProjectModelBinding":
        if self._closed:
            raise RuntimeError("qualified project model binding is closed")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


def bind_qualified_project_model(
    profile: ModelProviderProfile,
    *,
    closure_path: str | Path,
    request_root: str | Path,
    api_key: str = "",
    timeout_s: float | None = None,
    task_group_id: str = "project:model",
) -> QualifiedProjectModelBinding:
    """Bind one persisted qualified deployment to the public project model seam."""

    return QualifiedProjectModelBinding(
        profile,
        closure_path=closure_path,
        request_root=request_root,
        api_key=api_key,
        timeout_s=timeout_s,
        task_group_id=task_group_id,
    )


class DirectoryRunArtifactStoreBinding:
    """Owned public binding for one durable run-local artifact store.

    Downstream projects receive the existing RunArtifactStorePort while Noetrium
    retains ownership of the serial writer actor and its structured-concurrency
    lifetime. The binding intentionally delegates storage semantics to the
    canonical run-artifact composition rather than reimplementing persistence.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        run_id: str,
        queue_capacity: int | None = None,
        task_group_id: str = "project:run-artifacts",
    ) -> None:
        if not task_group_id.strip():
            raise ValueError("task_group_id must be non-empty")
        self._concurrency = build_concurrency_runtime(
            blocking_io_thread_name_prefix="run-artifact-project-binding",
            timer_name="run-artifact-project-binding-timer",
        )
        try:
            self._task_group = self._concurrency.open_task_group(task_group_id)
            self._store: RunArtifactStorePort = build_directory_run_artifact_store(
                root,
                run_id=run_id,
                task_group=self._task_group,
                queue_capacity=queue_capacity,
            )
        except BaseException:
            self._concurrency.close()
            raise
        self._closed = False

    @property
    def store(self) -> RunArtifactStorePort:
        if self._closed:
            raise RuntimeError("run artifact store binding is closed")
        return self._store

    def close(self) -> None:
        if self._closed:
            return
        self._concurrency.close()
        self._closed = True

    def __enter__(self) -> "DirectoryRunArtifactStoreBinding":
        if self._closed:
            raise RuntimeError("run artifact store binding is closed")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


def bind_directory_run_artifact_store(
    root: str | Path,
    *,
    run_id: str,
    queue_capacity: int | None = None,
    task_group_id: str = "project:run-artifacts",
) -> DirectoryRunArtifactStoreBinding:
    """Bind Noetrium's durable directory run-artifact authority for a project."""

    return DirectoryRunArtifactStoreBinding(
        root,
        run_id=run_id,
        queue_capacity=queue_capacity,
        task_group_id=task_group_id,
    )


__all__ = [
    "DirectoryRunArtifactStoreBinding",
    "MinecraftEnvironmentBinding",
    "ProjectTestStage",
    "ProjectTestStageReceipt",
    "QualifiedProjectModelBinding",
    "ResearchAction",
    "ResearchApplicationPort",
    "ResearchFacade",
    "ResearchOperationFailure",
    "ResearchRequest",
    "ResearchResult",
    "bind_bundled_minecraft_environment",
    "bind_directory_run_artifact_store",
    "bind_minecraft_environment",
    "bind_qualified_project_model",
    "bind_run_control_application",
]
