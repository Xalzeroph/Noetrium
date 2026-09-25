from __future__ import annotations

from typing import Protocol

from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionSpec

from .contracts import ServerBootstrapState, ServerBootstrapTransactionReport


class ServerBootstrapStatePort(Protocol):
    def load_or_create(self, initial: ServerBootstrapState) -> ServerBootstrapState: ...
    def write(self, state: ServerBootstrapState, *, expected_revision: int) -> ServerBootstrapState: ...


class ServerBootstrapTransactionPort(Protocol):
    def reconcile(
        self,
        *,
        control_id: str,
        runtime_manifest_digest: str,
        release_digest: str,
        session_policy_digest: str,
        spec: PersistentSessionSpec,
    ) -> ServerBootstrapTransactionReport: ...


__all__ = ["ServerBootstrapStatePort", "ServerBootstrapTransactionPort"]
