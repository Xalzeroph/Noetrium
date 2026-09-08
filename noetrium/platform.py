"""Stable product facade for applications built on Noetrium."""

from __future__ import annotations

from importlib import resources

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
from noetrium_platform.foundation.kernel.concurrency.composition import (
    build_concurrency_runtime,
)
from noetrium_platform.infrastructure.lifecycle.host.providers import (
    LocalOperatingSystemRoute,
)
from noetrium_platform.product.operator.runtime.run_control_application import (
    bind_run_control_application,
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


__all__ = [
    "MinecraftEnvironmentBinding",
    "ProjectTestStage",
    "ProjectTestStageReceipt",
    "ResearchAction",
    "ResearchApplicationPort",
    "ResearchFacade",
    "ResearchOperationFailure",
    "ResearchRequest",
    "ResearchResult",
    "bind_bundled_minecraft_environment",
    "bind_minecraft_environment",
    "bind_run_control_application",
]
