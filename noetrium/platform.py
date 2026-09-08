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


__all__ = [
    "MinecraftEnvironmentBinding",
    "ProjectTestStage", "ProjectTestStageReceipt", "ResearchAction",
    "ResearchApplicationPort", "ResearchFacade", "ResearchOperationFailure",
    "ResearchRequest", "ResearchResult", "bind_bundled_minecraft_environment",
    "bind_minecraft_environment", "bind_run_control_application",
]
