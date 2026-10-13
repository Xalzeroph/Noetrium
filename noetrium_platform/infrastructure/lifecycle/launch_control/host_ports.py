from __future__ import annotations

from typing import Protocol

from .contracts import RuntimeLaunchManifestPort


class HostRuntimeVerificationPort(Protocol):
    """Read-only host/runtime attestation used by the runtime state machine.

    Runtime Manager owns only *when* host evidence is required. Capture mechanics,
    receipt schemas, resource-delta policy, and evidence storage belong to the
    concrete host-verification adapter behind this port.
    """

    def verify_pre_start(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]: ...

    def verify_post_ready(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]: ...


__all__ = ["HostRuntimeVerificationPort"]
