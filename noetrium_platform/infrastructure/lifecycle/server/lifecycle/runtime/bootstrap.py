from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.infrastructure.lifecycle.host.bootstrap.api import ServerBootstrapTransactionPort
from noetrium_platform.infrastructure.lifecycle.session.api import (
    PersistentSessionHostPort,
    PersistentSessionReport,
    ServerSessionPolicy,
    process_environment_digest,
    RuntimeControllerCommand,
)
from ..api import (
    ServerReleaseDirectoryPort,
    ServerReleaseLayoutError,
    ServerRuntimeLaunchManifestMismatch,
    ServerRuntimeLaunchManifestPort,
    ServerSessionPolicyMismatch,
)
from noetrium_platform.foundation.scope.path.api import is_absolute_target_path


@dataclass(frozen=True, slots=True)
class ImmutableServerReleaseLayout:
    """Content-addressed target layout for code kept alive by a controller session."""

    root: Path

    def __post_init__(self) -> None:
        root = self.root.resolve()
        if not is_absolute_target_path(root):
            raise ValueError("server release root must be absolute")
        object.__setattr__(self, "root", root)

    def release_dir(self, release_digest: str) -> Path:
        if len(release_digest) != 64:
            raise ValueError("release digest must be SHA-256 hex")
        return self.root / "releases" / release_digest

    def require_release_dir(self, release_digest: str) -> Path:
        path = self.release_dir(release_digest)
        if not path.is_dir() or path.is_symlink():
            raise ServerReleaseLayoutError(f"immutable release directory missing/invalid: {path}")
        resolved = path.resolve()
        expected_parent = (self.root / "releases").resolve()
        if resolved.parent != expected_parent or resolved.name != release_digest:
            raise ServerReleaseLayoutError("release path must be a real content-addressed directory")
        return path


@dataclass(frozen=True, slots=True)
class ServerRuntimeLaunchReport:
    release_dir: Path | str
    runtime_manifest_digest: str
    server_session_policy_digest: str
    bootstrap_phase: str
    bootstrap_revision: int
    bootstrap_evidence_refs: tuple[str, ...]
    session: PersistentSessionReport


class ServerRuntimeBootstrap:
    """Bind an exact release and frozen controller command to server lifecycle."""

    CONFIG_KEY = "server_session"

    def __init__(
        self,
        layout: ServerReleaseDirectoryPort,
        session_host: PersistentSessionHostPort,
        bootstrap_transaction: ServerBootstrapTransactionPort,
        policy: ServerSessionPolicy | None = None,
    ) -> None:
        self.layout = layout
        self.session_host = session_host
        self.bootstrap_transaction = bootstrap_transaction
        if not session_host.transport_identity_verified:
            raise ServerSessionPolicyMismatch("production persistent-session transport identity is unverified")
        self.policy = policy or ServerSessionPolicy(
            session_host.transport_backend_id,
            session_host.transport_identity_digest,
        )
        if self.policy.backend_id != session_host.transport_backend_id:
            raise ServerSessionPolicyMismatch("server session policy backend does not match transport backend")
        if self.policy.transport_identity_digest != session_host.transport_identity_digest:
            raise ServerSessionPolicyMismatch("server session policy does not match transport identity")

    def _verify_manifest_policy(self, manifest: ServerRuntimeLaunchManifestPort) -> None:
        configs = dict(manifest.config_digests)
        actual = configs.get(self.CONFIG_KEY)
        expected = self.policy.digest()
        if actual != expected:
            raise ServerSessionPolicyMismatch(
                f"run launch manifest server_session digest mismatch: expected {expected}, got {actual}"
            )

    def ensure_controller(
        self,
        manifest: ServerRuntimeLaunchManifestPort,
        *,
        control_id: str,
        controller_environment: tuple[tuple[str, str], ...] = (),
    ) -> ServerRuntimeLaunchReport:
        self._verify_manifest_policy(manifest)
        if process_environment_digest(controller_environment) != manifest.command_environment_digest:
            raise ServerRuntimeLaunchManifestMismatch(
                "controller environment differs from the frozen run launch manifest"
            )
        release_dir = self.layout.require_release_dir(manifest.release_digest)
        command = RuntimeControllerCommand(
            manifest.command_argv,
            str(release_dir),
            controller_environment,
            manifest.launcher_binary_sha256,
        )
        spec = self.session_host.spec(manifest, control_id=control_id, command=command)
        transaction = self.bootstrap_transaction.reconcile(
            control_id=control_id,
            runtime_manifest_digest=manifest.digest(),
            release_digest=manifest.release_digest,
            session_policy_digest=self.policy.digest(),
            spec=spec,
        )
        return ServerRuntimeLaunchReport(
            Path(release_dir) if isinstance(release_dir, Path) else release_dir,
            manifest.digest(),
            self.policy.digest(),
            transaction.state.phase.value,
            transaction.state.revision,
            transaction.state.evidence_refs,
            transaction.session,
        )


__all__ = [
    "ImmutableServerReleaseLayout",
    "ServerReleaseLayoutError",
    "ServerRuntimeBootstrap",
    "ServerRuntimeLaunchManifestMismatch",
    "ServerRuntimeLaunchReport",
    "ServerSessionPolicyMismatch",
]
