from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

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
from noetrium_platform.infrastructure.lifecycle.process.api import (
    LocalCommandRunnerPort,
)

from ..api import (
    SoftwareActionKind,
    SoftwareEnvironmentSpec,
    SoftwareWorldPort,
)


def _require_relative_path(root: Path, value: object) -> Path:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise ValueError("software workspace path must be non-empty safe text")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError("software workspace path must be relative")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("software workspace path escapes workspace root") from exc
    return candidate


def _payload(request: ActionRequest) -> dict[str, object]:
    decoded = thaw_json(request.payload)
    if not isinstance(decoded, dict):
        raise TypeError("software action payload must be an object")
    return decoded


def _argv(value: object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or not value:
        raise ValueError("software execute/test/build requires non-empty argv")
    result = tuple(value)
    if any(type(item) is not str or not item or "\x00" in item for item in result):
        raise ValueError("software command argv must contain safe non-empty strings")
    return result


class LocalRepositorySoftwareProvider(EnvironmentProviderPort):
    """Local repository workspace provider over the shared process authority."""

    def __init__(
        self,
        *,
        root: str | Path,
        spec: SoftwareEnvironmentSpec,
        command_runner: LocalCommandRunnerPort,
        command_runner_identity_digest: str,
    ) -> None:
        if not isinstance(spec, SoftwareEnvironmentSpec):
            raise TypeError("local software provider requires SoftwareEnvironmentSpec")
        resolved = Path(root).resolve()
        if not resolved.is_dir():
            raise ValueError("local software workspace root must exist")
        declared = Path(spec.workspace_root).resolve()
        if declared != resolved:
            raise ValueError(
                "software workspace spec root must match provider workspace root"
            )
        if not callable(getattr(command_runner, "run", None)):
            raise TypeError(
                "local software provider requires command runner run()"
            )
        self._root = resolved
        self._spec = spec
        self._runner = command_runner
        self._runner_identity_digest = require_sha256(
            command_runner_identity_digest,
            "software command runner identity digest",
        )
        artifact_digest = canonical_digest({
            "spec_digest": spec.spec_digest,
            "workspace_root": str(resolved),
            "command_runner_identity_digest": self._runner_identity_digest,
        })
        self._identity = EnvironmentIdentity(
            environment_id=spec.environment_id,
            implementation_version=spec.revision,
            abi_version="environment.software.repository.v1",
            schema_version="1",
            artifact_digest=artifact_digest,
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
            "spec_digest": self._spec.spec_digest,
            "command_runner_identity_digest": self._runner_identity_digest,
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
            raise ValueError("software session_id must be non-empty")
        return _LocalRepositorySoftwareSession(
            root=self._root,
            spec=self._spec,
            command_runner=self._runner,
            identity=self._identity,
            capabilities=self._capabilities,
            session_id=session_id,
            provider_identity_digest=self.identity_digest,
        )


class _LocalRepositorySoftwareSession(
    SoftwareWorldPort,
    EnvironmentDiagnosticsPort,
):
    def __init__(
        self,
        *,
        root: Path,
        spec: SoftwareEnvironmentSpec,
        command_runner: LocalCommandRunnerPort,
        identity: EnvironmentIdentity,
        capabilities: EnvironmentProviderCapabilities,
        session_id: str,
        provider_identity_digest: str,
    ) -> None:
        self._root = root
        self._spec = spec
        self._runner = command_runner
        self._identity = identity
        self._capabilities = capabilities
        self._session_id = session_id
        self._provider_identity_digest = provider_identity_digest
        self._closed = False
        self._results: dict[str, ActionResult] = {}
        self._request_digests: dict[str, str] = {}

    @property
    def spec(self) -> SoftwareEnvironmentSpec:
        return self._spec

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "provider_identity_digest": self._provider_identity_digest,
            "session_id": self._session_id,
        })

    def observe(self, context: ExecutionContext) -> Observation:
        del context
        self._ensure_open()
        return self._workspace_observation("software-workspace-observation")

    def act(self, request: ActionRequest) -> ActionResult:
        self._ensure_open()
        if not isinstance(request, ActionRequest):
            raise TypeError("software environment act requires ActionRequest")
        digest = action_request_digest(request)
        previous_digest = self._request_digests.get(request.action_id)
        if previous_digest is not None:
            if previous_digest != digest:
                raise ActionIdentityViolation(
                    f"software action identity reused with drift: {request.action_id}"
                )
            return self._results[request.action_id]

        try:
            kind = SoftwareActionKind(request.action_type)
        except ValueError as exc:
            raise ValueError(
                f"unsupported software action type: {request.action_type}"
            ) from exc
        if self._spec.supported_actions and kind not in self._spec.supported_actions:
            raise ValueError(
                f"software action is not enabled by workspace spec: {kind.value}"
            )

        self._request_digests[request.action_id] = digest
        if kind is SoftwareActionKind.LIST:
            result = self._list(request)
        elif kind is SoftwareActionKind.READ:
            result = self._read(request)
        elif kind is SoftwareActionKind.EDIT:
            result = self._edit(request)
        else:
            result = self._run_command(request, kind)
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
            if (
                result.effect is not None
                and result.effect.effect_id == effect.effect_id
            ):
                if result.effect.request_digest != effect.request_digest:
                    raise ActionIdentityViolation(
                        "software effect request digest drift"
                    )
                return result.effect
        raise ActionIdentityViolation(
            "software effect does not identify a session action"
        )

    def diagnostics_snapshot(self) -> EnvironmentSessionDiagnostics:
        state_digest = self._workspace_state_digest()
        return EnvironmentSessionDiagnostics(
            session_id=self._session_id,
            environment=self._identity,
            generation=self._spec.revision,
            ready=not self._closed,
            closed=self._closed,
            capabilities=self._capabilities,
            state_digest=state_digest,
        )

    def close(self) -> None:
        self._closed = True

    def _list(self, request: ActionRequest) -> ActionResult:
        payload = _payload(request)
        suffix = payload.get("suffix")
        if suffix is not None and type(suffix) is not str:
            raise TypeError("software list suffix must be text or None")
        files = tuple(
            row["path"]
            for row in self._workspace_rows()
            if suffix is None or str(row["path"]).endswith(suffix)
        )
        observation = Observation(
            observation_id=f"software:{request.action_id}:list",
            generation=self._workspace_state_digest(),
            payload={
                "action": SoftwareActionKind.LIST.value,
                "files": files,
                "suffix": suffix,
            },
        )
        return ActionResult(
            action_id=request.action_id,
            accepted=True,
            observation=observation,
            effect=None,
            diagnostics={"state_digest": observation.generation},
        )

    def _read(self, request: ActionRequest) -> ActionResult:
        payload = _payload(request)
        path = _require_relative_path(self._root, payload.get("path"))
        if not path.is_file():
            raise FileNotFoundError(path)
        content = path.read_text(encoding="utf-8")
        observation = Observation(
            observation_id=f"software:{request.action_id}:read",
            generation=self._workspace_state_digest(),
            payload={
                "action": SoftwareActionKind.READ.value,
                "path": path.relative_to(self._root).as_posix(),
                "content": content,
                "sha256": sha256(content.encode("utf-8")).hexdigest(),
            },
        )
        return ActionResult(
            action_id=request.action_id,
            accepted=True,
            observation=observation,
            effect=None,
            diagnostics={"state_digest": observation.generation},
        )

    def _edit(self, request: ActionRequest) -> ActionResult:
        payload = _payload(request)
        path = _require_relative_path(self._root, payload.get("path"))
        content = payload.get("content")
        if type(content) is not str:
            raise TypeError("software edit content must be text")
        before = self._workspace_state_digest()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        after = self._workspace_state_digest()
        effect = EffectReceipt(
            effect_id=f"software-edit:{request.action_id}",
            request_digest=action_request_digest(request),
            effect_class=EffectClass.RECONCILABLE,
            certainty=EffectCertainty.EFFECT_CONFIRMED,
            provider_instance_id=(
                f"{self._identity.environment_id}:{self._session_id}"
            ),
            verification_required=False,
            before_artifact=before,
            after_artifact=after,
            provider_receipt=request.action_id,
        )
        return ActionResult(
            action_id=request.action_id,
            accepted=True,
            observation=self._workspace_observation(
                f"software:{request.action_id}:edit"
            ),
            effect=effect,
            diagnostics={
                "path": path.relative_to(self._root).as_posix(),
                "before_state_digest": before,
                "after_state_digest": after,
            },
        )

    def _run_command(
        self,
        request: ActionRequest,
        kind: SoftwareActionKind,
    ) -> ActionResult:
        payload = _payload(request)
        argv = _argv(payload.get("argv"))
        timeout_value = payload.get("timeout_seconds")
        timeout = None if timeout_value is None else float(timeout_value)
        before = self._workspace_state_digest()
        completed = self._runner.run(
            argv,
            cwd=self._root,
            timeout_seconds=timeout,
        )
        after = self._workspace_state_digest()
        effect = EffectReceipt(
            effect_id=f"software-{kind.value}:{request.action_id}",
            request_digest=action_request_digest(request),
            effect_class=EffectClass.RECONCILABLE,
            certainty=EffectCertainty.EFFECT_CONFIRMED,
            provider_instance_id=(
                f"{self._identity.environment_id}:{self._session_id}"
            ),
            verification_required=False,
            before_artifact=before,
            after_artifact=after,
            provider_receipt=request.action_id,
        )
        observation = Observation(
            observation_id=f"software:{request.action_id}:{kind.value}",
            generation=after,
            payload={
                "action": kind.value,
                "argv": argv,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "before_state_digest": before,
                "after_state_digest": after,
            },
        )
        return ActionResult(
            action_id=request.action_id,
            accepted=True,
            observation=observation,
            effect=effect,
            diagnostics={
                "returncode": completed.returncode,
                "before_state_digest": before,
                "after_state_digest": after,
            },
        )

    def _workspace_observation(self, observation_id: str) -> Observation:
        rows = self._workspace_rows()
        digest = canonical_digest(rows)
        return Observation(
            observation_id=observation_id,
            generation=digest,
            payload={
                "workspace_id": self._spec.environment_id,
                "revision": self._spec.revision,
                "state_digest": digest,
                "files": rows,
            },
        )

    def _workspace_state_digest(self) -> str:
        return canonical_digest(self._workspace_rows())

    def _workspace_rows(self) -> tuple[dict[str, object], ...]:
        rows: list[dict[str, object]] = []
        for path in sorted(self._root.rglob("*")):
            if ".git" in path.relative_to(self._root).parts:
                continue
            if path.is_symlink() or not path.is_file():
                continue
            data = path.read_bytes()
            rows.append({
                "path": path.relative_to(self._root).as_posix(),
                "size_bytes": len(data),
                "sha256": sha256(data).hexdigest(),
            })
        return tuple(rows)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError(
                f"software environment session is closed: {self._session_id}"
            )


__all__ = ["LocalRepositorySoftwareProvider"]
