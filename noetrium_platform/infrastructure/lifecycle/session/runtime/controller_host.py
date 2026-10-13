from __future__ import annotations

import hashlib
import re

from noetrium_platform.infrastructure.lifecycle.session.api import (
    PersistentSessionLaunchManifestPort,
    PersistentSessionReport,
    PersistentSessionRuntimePort,
    PersistentSessionSpec,
    RuntimeControllerCommand,
)

_SLUG = re.compile(r"[^A-Za-z0-9_.-]+")


class RuntimePersistentSessionHost:
    """Map frozen runtime-controller identity to the generic session runtime."""

    def __init__(self, sessions: PersistentSessionRuntimePort) -> None:
        self.sessions = sessions

    @property
    def transport_backend_id(self) -> str:
        return self.sessions.backend_id

    @property
    def transport_identity_digest(self) -> str:
        return self.sessions.transport_identity_digest

    @property
    def transport_identity_verified(self) -> bool:
        return self.sessions.transport_identity_verified

    @staticmethod
    def session_name(control_id: str, manifest_digest: str) -> str:
        slug = _SLUG.sub("-", control_id).strip("-._")[:32] or "runtime"
        control_hash = hashlib.sha256(control_id.encode("utf-8")).hexdigest()[:8]
        return f"rp-{slug}-{control_hash}-{manifest_digest[:12]}"

    def spec(
        self,
        manifest: PersistentSessionLaunchManifestPort,
        *,
        control_id: str,
        command: RuntimeControllerCommand,
    ) -> PersistentSessionSpec:
        digest = manifest.digest()
        return PersistentSessionSpec(
            self.session_name(control_id, digest),
            command.argv,
            command.cwd,
            control_id,
            digest,
            command.digest(),
            command.environment,
        )

    def ensure(
        self,
        manifest: PersistentSessionLaunchManifestPort,
        *,
        control_id: str,
        command: RuntimeControllerCommand,
    ) -> PersistentSessionReport:
        return self.sessions.ensure(self.spec(manifest, control_id=control_id, command=command))


__all__ = ["RuntimePersistentSessionHost"]
