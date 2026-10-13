from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from noetrium_platform.capabilities.environment.api import EnvironmentSession
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.substrate.api import NetworkEndpoint, ServiceReadyObservation

from ..api import (
    MinecraftBranchRuntimeFactoryPort,
    MinecraftBranchRuntimePort,
    MinecraftBranchRuntimeRequest,
    MinecraftBranchServerFactoryPort,
    MinecraftCheckpointPort,
    MinecraftEnvironmentRuntimeBinding,
    MinecraftServerSpec,
    MinecraftServerLifecyclePort,
    MinecraftServerReadinessEvidencePort,
    MinecraftSessionServices,
)
from .environment import MinecraftEnvironmentAssembly
from ..runtime import MinecraftEnvironmentImplementation, MinecraftEnvironmentRuntime
class MinecraftBranchRuntimeError(RuntimeError):
    """A branch runtime failed and its cleanup may also require inspection."""

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        cause: BaseException | None = None,
        cleanup_errors: tuple[BaseException, ...] = (),
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.cause = cause
        self.cleanup_errors = cleanup_errors


class MinecraftBranchEnvironmentFactoryPort(Protocol):
    def compose(
        self,
        environment: NoetriumUnit,
        runtime_binding: MinecraftEnvironmentRuntimeBinding,
        *,
        checkpoint: MinecraftCheckpointPort | None = None,
    ) -> MinecraftEnvironmentAssembly: ...


class MinecraftBranchCheckpointFactoryPort(Protocol):
    def create(
        self,
        *,
        server: MinecraftServerLifecyclePort,
        server_spec: MinecraftServerSpec,
        environment_generation: str,
        readiness_evidence: MinecraftServerReadinessEvidencePort,
    ) -> MinecraftCheckpointPort: ...
class _MinecraftReadinessEvidence(MinecraftServerReadinessEvidencePort):
    """READY observation evidence; never a second endpoint authority."""

    def __init__(
        self,
        *,
        endpoint: NetworkEndpoint,
        rcon_endpoint: NetworkEndpoint | None,
        environment_generation: str,
    ) -> None:
        self.endpoint = endpoint
        self.rcon_endpoint = rcon_endpoint
        self._environment_generation = environment_generation
        self._last_digest: str | None = None

    @property
    def last_digest(self) -> str | None:
        return self._last_digest

    def record_ready(self, readiness: ServiceReadyObservation) -> None:
        if not isinstance(readiness, ServiceReadyObservation):
            raise MinecraftBranchRuntimeError(
                "branch readiness did not return typed ServiceReadyObservation",
                phase="observe",
            )
        self._last_digest = canonical_digest(
            {
                "contract_digest": readiness.contract_digest,
                "process": readiness.process,
                "ready_evidence_ref": readiness.ready_evidence_ref,
                "ready_at": readiness.ready_at,
                "environment_generation": self._environment_generation,
                "endpoint": self.endpoint,
                "rcon_endpoint": self.rcon_endpoint,
            }
        )
class MinecraftBranchRuntimeBinding(MinecraftBranchRuntimePort):
    """Own one branch server/session; resource claims are owned above by Authority."""

    def __init__(
        self,
        *,
        readiness_evidence: _MinecraftReadinessEvidence,
        implementation: MinecraftEnvironmentImplementation,
        environment_runtime: MinecraftEnvironmentRuntime,
        server: MinecraftServerLifecyclePort,
        session_id: str,
    ) -> None:
        self._readiness_evidence = readiness_evidence
        self.implementation = implementation
        self._environment_runtime = environment_runtime
        self._server = server
        self._session_id = session_id
        self._session: EnvironmentSession | None = None
        self._session_closed = False
        self._closed = False

    @property
    def endpoint(self) -> NetworkEndpoint:
        return self._readiness_evidence.endpoint

    @property
    def rcon_endpoint(self) -> NetworkEndpoint | None:
        return self._readiness_evidence.rcon_endpoint

    @property
    def environment_generation(self) -> str:
        return self.implementation.identity.artifact_digest
    def open_session(self, services: MinecraftSessionServices) -> EnvironmentSession:
        if self._closed:
            raise MinecraftBranchRuntimeError(
                "branch runtime is closed",
                phase="start",
            )
        if self._session is not None:
            return self._session
        try:
            # Physical start/stop belongs exclusively to Resource Authority's
            # minecraft-server provider. The branch only consumes READY evidence.
            readiness = self._server.verify_ready()
            self._readiness_evidence.record_ready(readiness)
            self._session = self._environment_runtime.open_session(
                self.implementation,
                session_id=self._session_id,
                services=services,
            )
            return self._session
        except BaseException as exc:
            try:
                self.close()
            except BaseException as cleanup_exc:
                raise MinecraftBranchRuntimeError(
                    "branch runtime start failed and cleanup failed",
                    phase="start",
                    cause=exc,
                    cleanup_errors=(cleanup_exc,),
                ) from exc
            raise MinecraftBranchRuntimeError(
                "branch runtime start failed",
                phase="start",
                cause=exc,
            ) from exc

    def close(self) -> None:
        if self._closed:
            return
        errors: list[BaseException] = []
        if self._session is not None and not self._session_closed:
            try:
                self._session.close()
            except BaseException as exc:
                raise MinecraftBranchRuntimeError(
                    "branch runtime close failed before session convergence",
                    phase="close",
                    cleanup_errors=(exc,),
                ) from exc
            self._session_closed = True
        if errors:
            raise MinecraftBranchRuntimeError(
                f"branch runtime close failed ({len(errors)} cleanup errors)",
                phase="close",
                cleanup_errors=tuple(errors),
            ) from errors[0]
        self._closed = self._session is None or self._session_closed
        if not self._closed:
            raise MinecraftBranchRuntimeError(
                "branch runtime close did not converge",
                phase="close",
            )


class MinecraftBranchRuntimeFactory(MinecraftBranchRuntimeFactoryPort):
    """Compose one branch from Authority-admitted immutable endpoint facts."""

    def __init__(
        self,
        *,
        environment_factory: MinecraftBranchEnvironmentFactoryPort,
        checkpoint_factory: MinecraftBranchCheckpointFactoryPort | None = None,
        action_recovery_root: str | None = None,
    ) -> None:
        self._environment_factory = environment_factory
        self._checkpoint_factory = checkpoint_factory
        self._action_recovery_root = action_recovery_root
    def open_bound(
        self,
        request: MinecraftBranchRuntimeRequest,
        *,
        server: MinecraftServerLifecyclePort,
        endpoint: NetworkEndpoint,
        rcon_endpoint: NetworkEndpoint | None = None,
    ) -> MinecraftBranchRuntimeBinding:
        if not all(callable(getattr(server, name, None)) for name in ("verify_ready", "stop")):
            raise TypeError("Minecraft branch requires a bound server lifecycle")
        if not isinstance(endpoint, NetworkEndpoint):
            raise TypeError("Minecraft branch requires NetworkEndpoint")
        if rcon_endpoint is not None and not isinstance(
            rcon_endpoint,
            NetworkEndpoint,
        ):
            raise TypeError(
                "Minecraft branch RCON endpoint must be NetworkEndpoint"
            )
        if (
            request.server_template.rcon_endpoint is None
        ) != (rcon_endpoint is None):
            raise ValueError(
                "Minecraft branch RCON endpoint must match server requirement"
            )

        bridge_spec = request.environment_runtime_template.bridge
        if (
            bridge_spec.action_recovery_root is None
            and self._action_recovery_root is not None
        ):
            bridge_spec = replace(
                bridge_spec,
                action_recovery_root=self._action_recovery_root,
            )
        environment_runtime_binding = replace(
            request.environment_runtime_template,
            endpoint=replace(
                request.environment_runtime_template.endpoint,
                host=endpoint.host,
                port=endpoint.port,
            ),
            bridge=bridge_spec,
        )
        server_spec = replace(
            request.server_template,
            host=endpoint.host,
            port=endpoint.port,
            workdir=request.branch.workdir,
            level_name=request.branch.level_name,
        )
        if rcon_endpoint is not None:
            assert server_spec.rcon_endpoint is not None
            server_spec = replace(
                server_spec,
                rcon_endpoint=replace(
                    server_spec.rcon_endpoint,
                    host=rcon_endpoint.host,
                    port=rcon_endpoint.port,
                ),
            )

        environment_generation = request.environment.unit_digest
        readiness_evidence = _MinecraftReadinessEvidence(
            endpoint=endpoint,
            rcon_endpoint=rcon_endpoint,
            environment_generation=environment_generation,
        )
        checkpoint = None
        if self._checkpoint_factory is not None:
            checkpoint = self._checkpoint_factory.create(
                server=server,
                server_spec=server_spec,
                environment_generation=environment_generation,
                readiness_evidence=readiness_evidence,
            )
        environment = self._environment_factory.compose(
            request.environment,
            environment_runtime_binding,
            checkpoint=checkpoint,
        )
        if (
            environment.implementation.identity.artifact_digest
            != environment_generation
        ):
            raise MinecraftBranchRuntimeError(
                "branch environment generation drifted during composition",
                phase="compose",
            )
        return MinecraftBranchRuntimeBinding(
            readiness_evidence=readiness_evidence,
            implementation=environment.implementation,
            environment_runtime=environment.runtime,
            server=server,
            session_id=request.session_id,
        )
__all__ = [
    "MinecraftBranchEnvironmentFactoryPort",
    "MinecraftBranchCheckpointFactoryPort",
    "MinecraftBranchRuntimeBinding",
    "MinecraftBranchRuntimeError",
    "MinecraftBranchRuntimeFactory",
]
