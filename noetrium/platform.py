"""Stable product facade for applications built on Noetrium."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
import shutil
from uuid import uuid4

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
    MinecraftCheckpointPort,
    MinecraftDiagnosticsPort,
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
    PersistedQualifiedModelEndpointBinding,
    build_openai_compatible_qualified_endpoint,
    load_qualified_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.providers import (
    DirectoryRuntimeCanaryEvidenceStore,
    DirectoryRuntimeQualificationEvidenceStore,
)
from noetrium_platform.capabilities.model.serving.runtime.admission import ModelAdmissionRegistry
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.infrastructure.lifecycle.host.providers import LocalOperatingSystemRoute
from noetrium_platform.product.operator.runtime.run_control_application import (
    bind_run_control_application,
)


class MinecraftEnvironmentBinding:
    """Project-owned Minecraft provider binding over Noetrium runtime authorities."""

    def __init__(
        self,
        spec: MinecraftEnvironmentSpec,
        *,
        diagnostics: MinecraftDiagnosticsPort | None = None,
        checkpoint: MinecraftCheckpointPort | None = None,
        task_group_id: str | None = None,
    ) -> None:
        if not isinstance(spec, MinecraftEnvironmentSpec):
            raise TypeError("Minecraft environment binding requires MinecraftEnvironmentSpec")
        self._concurrency = build_concurrency_runtime()
        self._task_group = self._concurrency.open_task_group(
            task_group_id or f"project-minecraft-{uuid4().hex}"
        )
        try:
            self._assembly = compose_minecraft_environment(
                spec,
                operating_system=LocalOperatingSystemRoute(),
                diagnostics=diagnostics,
                checkpoint=checkpoint,
                task_group=self._task_group,
            )
        except BaseException:
            self._concurrency.close()
            raise
        self._sessions: list[EnvironmentSession] = []
        self._closed = False
        supported = [
            EnvironmentCapability.RECONCILE,
            EnvironmentCapability.DIAGNOSTICS,
            EnvironmentCapability.QUERY,
        ]
        if checkpoint is not None:
            supported.extend((EnvironmentCapability.SNAPSHOT, EnvironmentCapability.RESTORE))
        self._capabilities = EnvironmentProviderCapabilities(tuple(supported))

    @property
    def spec(self) -> MinecraftEnvironmentSpec:
        return self._assembly.implementation.spec

    @property
    def identity(self) -> EnvironmentIdentity:
        return self._assembly.implementation.identity

    @property
    def capabilities(self) -> EnvironmentProviderCapabilities:
        return self._capabilities

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
        errors: list[BaseException] = []
        for session in reversed(self._sessions):
            try:
                session.close()
            except BaseException as exc:
                errors.append(exc)
        try:
            self._concurrency.close()
        except BaseException as exc:
            errors.append(exc)
        self._closed = True
        if errors:
            raise ExceptionGroup("Minecraft environment binding close failed", errors)

    def __enter__(self) -> "MinecraftEnvironmentBinding":
        if self._closed:
            raise RuntimeError("Minecraft environment binding is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def bind_minecraft_environment(
    spec: MinecraftEnvironmentSpec,
    *,
    diagnostics: MinecraftDiagnosticsPort | None = None,
    checkpoint: MinecraftCheckpointPort | None = None,
    task_group_id: str | None = None,
) -> MinecraftEnvironmentBinding:
    """Bind an explicit Minecraft spec to Noetrium-owned local runtime authorities."""

    return MinecraftEnvironmentBinding(
        spec,
        diagnostics=diagnostics,
        checkpoint=checkpoint,
        task_group_id=task_group_id,
    )


def bind_bundled_minecraft_environment(
    *,
    host: str = "127.0.0.1",
    port: int = 25565,
    username: str = "ResearchBot",
    auth: str = "offline",
    version: str = "",
    node_executable: str | None = None,
    action_recovery_root: str | None = None,
    connect_timeout_s: float = 45.0,
    command_timeout_s: float = 45.0,
    diagnostics: MinecraftDiagnosticsPort | None = None,
    checkpoint: MinecraftCheckpointPort | None = None,
    task_group_id: str | None = None,
) -> MinecraftEnvironmentBinding:
    """Bind Noetrium's packaged Mineflayer bridge without exposing provider paths."""

    bridge_root = Path(
        str(
            resources.files("noetrium_platform.capabilities.environment.minecraft.providers")
            .joinpath("assets")
            .joinpath("mineflayer_bridge")
        )
    ).resolve()
    bridge_script = bridge_root / "bridge.js"
    if not bridge_script.is_file():
        raise RuntimeError("Noetrium bundled Minecraft bridge asset is unavailable")
    executable = node_executable or shutil.which("node")
    if not executable:
        raise RuntimeError("Node.js executable is required for the bundled Minecraft bridge")
    spec = MinecraftEnvironmentSpec(
        endpoint=MinecraftEndpointSpec(host=host, port=port),
        bridge=MinecraftBridgeSpec(
            command=(executable, str(bridge_script)),
            cwd=str(bridge_root),
            action_recovery_root=action_recovery_root,
            connect_timeout_s=connect_timeout_s,
            command_timeout_s=command_timeout_s,
        ),
        agent=MinecraftAgentSpec(username=username, auth=auth, version=version),
    )
    return bind_minecraft_environment(
        spec,
        diagnostics=diagnostics,
        checkpoint=checkpoint,
        task_group_id=task_group_id,
    )


class QualifiedProjectModelBinding:
    """Own one project-facing binding over a persisted qualified deployment closure."""

    def __init__(
        self,
        profile: ModelProviderProfile,
        *,
        closure_path: str | Path,
        request_root: str | Path,
        api_key: str = "",
        timeout_s: float | None = None,
        task_group_id: str | None = None,
    ) -> None:
        if not isinstance(profile, ModelProviderProfile):
            raise TypeError("profile must be ModelProviderProfile")
        if timeout_s is not None and timeout_s <= 0:
            raise ValueError("timeout_s must be positive when provided")
        self._profile = profile
        self._concurrency = build_concurrency_runtime()
        self._admission = ModelAdmissionRegistry()
        try:
            self._task_group = self._concurrency.open_task_group(
                task_group_id or f"project-model-{uuid4().hex}"
            )
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
                profile, bindings, endpoint_factory, self._model_requests
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
        self, requirement: ModelCapabilityRequirement
    ) -> tuple[ModelBindingDiagnostic, ...]:
        if self._closed:
            raise RuntimeError("qualified project model binding is closed")
        return self._provider.diagnose(requirement)

    def close(self) -> None:
        if self._closed:
            return
        errors: list[BaseException] = []
        try:
            self._admission.close()
        except BaseException as exc:
            errors.append(exc)
        try:
            self._concurrency.close()
        except BaseException as exc:
            errors.append(exc)
        self._closed = True
        if errors:
            raise ExceptionGroup("qualified project model binding close failed", errors)

    def __enter__(self) -> "QualifiedProjectModelBinding":
        if self._closed:
            raise RuntimeError("qualified project model binding is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def bind_qualified_project_model(
    profile: ModelProviderProfile,
    *,
    closure_path: str | Path,
    request_root: str | Path,
    api_key: str = "",
    timeout_s: float | None = None,
    task_group_id: str | None = None,
) -> QualifiedProjectModelBinding:
    """Bind a persisted qualified model deployment through Noetrium authorities."""

    return QualifiedProjectModelBinding(
        profile,
        closure_path=closure_path,
        request_root=request_root,
        api_key=api_key,
        timeout_s=timeout_s,
        task_group_id=task_group_id,
    )


__all__ = [
    "MinecraftEnvironmentBinding",
    "QualifiedProjectModelBinding",
    "ProjectTestStage", "ProjectTestStageReceipt", "ResearchAction",
    "ResearchApplicationPort", "ResearchFacade", "ResearchOperationFailure",
    "ResearchRequest", "ResearchResult", "bind_bundled_minecraft_environment",
    "bind_minecraft_environment", "bind_qualified_project_model",
    "bind_run_control_application",
]
