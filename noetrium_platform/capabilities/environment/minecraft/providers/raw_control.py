from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.environment.api import (
    ActionIdentityViolation,
    ActionRequest,
    ActionResult,
    EnvironmentCapability,
    EnvironmentDiagnosticsPort,
    EnvironmentIdentity,
    EnvironmentProviderCapabilities,
    EnvironmentProviderPort,
    EnvironmentSession,
    EnvironmentSessionDiagnostics,
    EnvironmentSessionServices,
    Observation,
    action_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    canonical_digest,
    require_sha256,
    thaw_json,
)

from ..api.raw_control import (
    MinecraftRawControlBackendPort,
    MinecraftRawControlCommand,
    MinecraftRawControlObservation,
    validate_raw_control_backend,
)


class MinecraftRawControlProvider(EnvironmentProviderPort):
    """Environment provider for raw-pixel / keyboard-mouse Minecraft agents."""

    ACTION_TYPE = "minecraft_raw_control"

    def __init__(
        self,
        *,
        backend: MinecraftRawControlBackendPort,
        environment_id: str = "minecraft.raw_control",
        implementation_version: str = "1",
    ) -> None:
        backend_digest = validate_raw_control_backend(backend)
        if type(environment_id) is not str or not environment_id.strip():
            raise ValueError("Minecraft raw-control environment_id is required")
        if type(implementation_version) is not str or not implementation_version.strip():
            raise ValueError(
                "Minecraft raw-control implementation_version is required"
            )
        self._backend = backend
        self._backend_digest = backend_digest
        self._identity = EnvironmentIdentity(
            environment_id=environment_id.strip(),
            implementation_version=implementation_version.strip(),
            abi_version="environment.minecraft.raw-control.v1",
            schema_version="1",
            artifact_digest=canonical_digest({
                "backend_identity_digest": backend_digest,
                "provider_revision": 1,
            }),
        )
        self._capabilities = EnvironmentProviderCapabilities((
            EnvironmentCapability.RECONCILE,
            EnvironmentCapability.DIAGNOSTICS,
        ))

    @property
    def identity(self) -> EnvironmentIdentity:
        return self._identity

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "environment": self._identity,
            "backend_identity_digest": self._backend_digest,
        })

    @property
    def capabilities(self) -> EnvironmentProviderCapabilities:
        return self._capabilities

    def open_session(
        self,
        *,
        session_id: str,
        services: EnvironmentSessionServices,
    ) -> EnvironmentSession:
        del services
        if type(session_id) is not str or not session_id.strip():
            raise ValueError("Minecraft raw-control session_id is required")
        return _MinecraftRawControlSession(
            backend=self._backend,
            backend_identity_digest=self._backend_digest,
            environment=self._identity,
            capabilities=self._capabilities,
            session_id=session_id.strip(),
        )


class _MinecraftRawControlSession(
    EnvironmentSession,
    EnvironmentDiagnosticsPort,
):
    def __init__(
        self,
        *,
        backend: MinecraftRawControlBackendPort,
        backend_identity_digest: str,
        environment: EnvironmentIdentity,
        capabilities: EnvironmentProviderCapabilities,
        session_id: str,
    ) -> None:
        self._backend = backend
        self._backend_identity_digest = require_sha256(
            backend_identity_digest,
            "Minecraft raw-control backend identity_digest",
        )
        self._environment = environment
        self._capabilities = capabilities
        self._session_id = session_id
        self._observation: MinecraftRawControlObservation | None = None
        self._sequence = 0
        self._closed = False
        self._results: dict[str, ActionResult] = {}
        self._request_digests: dict[str, str] = {}

    def observe(self, context: ExecutionContext) -> Observation:
        self._ensure_open()
        if self._observation is None:
            value = self._backend.reset(
                session_id=self._session_id,
                context=context,
            )
            if not isinstance(value, MinecraftRawControlObservation):
                raise TypeError(
                    "Minecraft raw-control reset must return typed observation"
                )
            self._observation = value
        return self._generic_observation(
            self._observation,
            observation_id=(
                f"minecraft-raw:{self._session_id}:observe:{self._sequence}"
            ),
        )

    def act(self, request: ActionRequest) -> ActionResult:
        self._ensure_open()
        if not isinstance(request, ActionRequest):
            raise TypeError(
                "Minecraft raw-control act requires ActionRequest"
            )
        if request.action_type != MinecraftRawControlProvider.ACTION_TYPE:
            raise ValueError(
                "Minecraft raw-control provider accepts only "
                f"{MinecraftRawControlProvider.ACTION_TYPE}"
            )
        request_digest = action_request_digest(request)
        prior = self._request_digests.get(request.action_id)
        if prior is not None:
            if prior != request_digest:
                raise ActionIdentityViolation(
                    "Minecraft raw-control action id reused with drift"
                )
            return self._results[request.action_id]

        payload = thaw_json(request.payload)
        if not isinstance(payload, dict):
            raise TypeError(
                "Minecraft raw-control action payload must be object"
            )
        controls = payload.get("controls")
        if not isinstance(controls, Mapping):
            raise TypeError(
                "Minecraft raw-control payload requires controls object"
            )
        if self._observation is None:
            self.observe(request.context)
        assert self._observation is not None
        before = self._observation.observation_digest
        command = MinecraftRawControlCommand(
            command_id=request.action_id,
            sequence=self._sequence,
            controls=dict(controls),
        )
        value = self._backend.step(
            command,
            context=request.context,
        )
        if not isinstance(value, MinecraftRawControlObservation):
            raise TypeError(
                "Minecraft raw-control step must return typed observation"
            )
        self._sequence += 1
        self._observation = value
        observation = self._generic_observation(
            value,
            observation_id=(
                f"minecraft-raw:{self._session_id}:step:{self._sequence}"
            ),
        )
        effect = EffectReceipt(
            effect_id=f"minecraft-raw:{request.action_id}",
            request_digest=request_digest,
            effect_class=EffectClass.RECONCILABLE,
            certainty=EffectCertainty.EFFECT_CONFIRMED,
            provider_instance_id=(
                f"{self._environment.environment_id}:{self._session_id}"
            ),
            verification_required=False,
            before_artifact=before,
            after_artifact=value.observation_digest,
            provider_receipt=command.command_digest,
        )
        result = ActionResult(
            action_id=request.action_id,
            accepted=True,
            observation=observation,
            effect=effect,
            diagnostics={
                "sequence": self._sequence,
                "command_digest": command.command_digest,
                "backend_identity_digest": self._backend_identity_digest,
            },
        )
        self._request_digests[request.action_id] = request_digest
        self._results[request.action_id] = result
        return result

    def reconcile(
        self,
        effect: EffectReceipt,
        context: ExecutionContext,
    ) -> EffectReceipt:
        del context
        self._ensure_open()
        for result in self._results.values():
            if result.effect is None:
                continue
            if result.effect.effect_id != effect.effect_id:
                continue
            if result.effect.request_digest != effect.request_digest:
                raise ActionIdentityViolation(
                    "Minecraft raw-control effect request digest drift"
                )
            return result.effect
        raise ActionIdentityViolation(
            "Minecraft raw-control effect does not identify a session action"
        )

    def diagnostics_snapshot(self) -> EnvironmentSessionDiagnostics:
        state_digest = (
            None
            if self._observation is None
            else self._observation.observation_digest
        )
        return EnvironmentSessionDiagnostics(
            session_id=self._session_id,
            environment=self._environment,
            generation=str(self._sequence),
            ready=not self._closed,
            closed=self._closed,
            capabilities=self._capabilities,
            state_digest=state_digest,
        )

    def close(self) -> None:
        if not self._closed:
            self._backend.close()
            self._closed = True

    def _generic_observation(
        self,
        value: MinecraftRawControlObservation,
        *,
        observation_id: str,
    ) -> Observation:
        return Observation(
            observation_id=observation_id,
            generation=value.observation_digest,
            payload={
                "minecraft_raw_observation": value.payload(),
                "frame_artifact_ref": value.frame_artifact_ref,
                "state": thaw_json(value.state),
                "reward": value.reward,
                "success": value.success,
                "done": value.done,
                "terminated": value.terminated,
                "truncated": value.truncated,
                "backend_identity_digest": self._backend_identity_digest,
            },
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError(
                f"Minecraft raw-control session is closed: {self._session_id}"
            )


__all__ = ["MinecraftRawControlProvider"]
