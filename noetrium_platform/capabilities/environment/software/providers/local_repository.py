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
from noetrium_platform.foundation.kernel.kernel.durability import atomic_replace_bytes
from noetrium_platform.substrate.api import (
    LocalCommandRunnerPort,
    LocalCommandTimeoutError,
)

from ..api import (
    SoftwareActionKind,
    SoftwareActionTimeoutError,
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


def _text_decision_view(text: str, *, max_chars: int) -> dict[str, object]:
    total = len(text)
    if total <= max_chars:
        return {
            "text": text,
            "total_chars": total,
            "truncated": False,
        }
    head_chars = max_chars // 3
    tail_chars = max_chars - head_chars
    elided = total - max_chars
    preview = (
        text[:head_chars]
        + f"\n...[{elided} chars elided; request a narrower range/filter]...\n"
        + text[-tail_chars:]
    )
    return {
        "text": preview,
        "total_chars": total,
        "truncated": True,
        "elided_chars": elided,
    }


def _positive_int(value: object, name: str, *, default: int | None = None) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"software {name} must be a positive integer")
    return value


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
        prefix = payload.get("prefix")
        contains = payload.get("contains")
        for name, value in (("suffix", suffix), ("prefix", prefix), ("contains", contains)):
            if value is not None and type(value) is not str:
                raise TypeError(f"software list {name} must be text or None")
        requested_limit = _positive_int(payload.get("limit"), "list limit")
        files = tuple(
            str(row["path"])
            for row in self._workspace_rows()
            if (suffix is None or str(row["path"]).endswith(suffix))
            and (prefix is None or str(row["path"]).startswith(prefix))
            and (contains is None or contains in str(row["path"]))
        )
        policy_limit = self._spec.context_policy.max_list_files
        view_limit = min(requested_limit or policy_limit, policy_limit)
        visible = files[:view_limit]
        observation = Observation(
            observation_id=f"software:{request.action_id}:list",
            generation=self._workspace_state_digest(),
            payload={
                "action": SoftwareActionKind.LIST.value,
                "files": files,
                "suffix": suffix,
                "prefix": prefix,
                "contains": contains,
                "decision_view": {
                    "kind": "software_list.v1",
                    "files": visible,
                    "matched_count": len(files),
                    "shown_count": len(visible),
                    "truncated": len(visible) < len(files),
                    "filters": {
                        "suffix": suffix,
                        "prefix": prefix,
                        "contains": contains,
                    },
                },
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
        lines = content.splitlines(keepends=True)
        start_line = _positive_int(payload.get("start_line"), "read start_line", default=1)
        end_line = _positive_int(payload.get("end_line"), "read end_line")
        assert start_line is not None
        if end_line is not None and end_line < start_line:
            raise ValueError("software read end_line must be >= start_line")
        selected = "".join(lines[start_line - 1:end_line])
        preview = _text_decision_view(
            selected,
            max_chars=self._spec.context_policy.max_text_chars,
        )
        observation = Observation(
            observation_id=f"software:{request.action_id}:read",
            generation=self._workspace_state_digest(),
            payload={
                "action": SoftwareActionKind.READ.value,
                "path": path.relative_to(self._root).as_posix(),
                "content": content,
                "sha256": sha256(content.encode("utf-8")).hexdigest(),
                "decision_view": {
                    "kind": "software_read.v1",
                    "path": path.relative_to(self._root).as_posix(),
                    "content": preview["text"],
                    "total_lines": len(lines),
                    "requested_lines": {
                        "start": start_line,
                        "end": end_line,
                    },
                    "selected_chars": len(selected),
                    "truncated": preview["truncated"],
                    "total_chars": preview["total_chars"],
                    "elided_chars": preview.get("elided_chars", 0),
                },
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
        encoded = content.encode("utf-8")
        atomic_replace_bytes(path, encoded)
        after_rows = self._workspace_rows()
        after = canonical_digest(after_rows)
        relative_path = path.relative_to(self._root).as_posix()
        workspace_summary = {
            "file_count": len(after_rows),
            "total_bytes": sum(int(row["size_bytes"]) for row in after_rows),
        }
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
                f"software:{request.action_id}:edit",
                rows=after_rows,
                digest=after,
                decision_view={
                    "kind": "software_edit.v1",
                    "path": relative_path,
                    "size_bytes": len(encoded),
                    "line_count": len(content.splitlines()),
                    "workspace": workspace_summary,
                },
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
        try:
            completed = self._runner.run(
                argv,
                cwd=self._root,
                timeout_seconds=timeout,
            )
        except LocalCommandTimeoutError as exc:
            raise SoftwareActionTimeoutError(
                f"software {kind.value} action timed out"
            ) from exc
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
        stdout_view = _text_decision_view(
            completed.stdout,
            max_chars=self._spec.context_policy.max_text_chars,
        )
        stderr_view = _text_decision_view(
            completed.stderr,
            max_chars=self._spec.context_policy.max_text_chars,
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
                "decision_view": {
                    "kind": f"software_{kind.value}.v1",
                    "argv": argv,
                    "returncode": completed.returncode,
                    "stdout": stdout_view,
                    "stderr": stderr_view,
                },
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

    def _workspace_observation(
        self,
        observation_id: str,
        *,
        rows: tuple[dict[str, object], ...] | None = None,
        digest: str | None = None,
        decision_view: dict[str, object] | None = None,
    ) -> Observation:
        resolved_rows = self._workspace_rows() if rows is None else rows
        resolved_digest = (
            canonical_digest(resolved_rows) if digest is None else digest
        )
        if decision_view is None:
            visible_rows = resolved_rows[: self._spec.context_policy.max_workspace_files]
            decision_view = {
                "kind": "software_workspace.v1",
                "workspace_id": self._spec.environment_id,
                "revision": self._spec.revision,
                "file_count": len(resolved_rows),
                "total_bytes": sum(
                    int(row["size_bytes"]) for row in resolved_rows
                ),
                "files": tuple(
                    (row["path"], row["size_bytes"])
                    for row in visible_rows
                ),
                "shown_count": len(visible_rows),
                "truncated": len(visible_rows) < len(resolved_rows),
            }
        return Observation(
            observation_id=observation_id,
            generation=resolved_digest,
            payload={
                "workspace_id": self._spec.environment_id,
                "revision": self._spec.revision,
                "state_digest": resolved_digest,
                "files": resolved_rows,
                "decision_view": decision_view,
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
