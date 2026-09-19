from __future__ import annotations

from dataclasses import dataclass
import math

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.scope.path.api import is_absolute_target_path


@dataclass(frozen=True, slots=True)
class ServiceLaunchContract:
    service_id: str
    generation: str
    executable: str
    argv: tuple[str, ...]
    cwd: str
    environment_digest: str
    artifact_digest: str
    runtime_identity_digest: str
    readiness_timeout_s: float
    stop_timeout_s: float
    heartbeat_interval_s: float

    def __post_init__(self) -> None:
        if not self.service_id or not self.generation:
            raise ValueError("service identity required")
        if not is_absolute_target_path(self.executable):
            raise ValueError("service executable must be an absolute path")
        if not self.argv or self.argv[0] != self.executable:
            raise ValueError("argv[0] must equal frozen executable")
        if not is_absolute_target_path(self.cwd):
            raise ValueError("service cwd must be an absolute path")
        if any(
            not math.isfinite(float(value)) or value <= 0
            for value in (self.readiness_timeout_s, self.stop_timeout_s, self.heartbeat_interval_s)
        ):
            raise ValueError("service timeouts/heartbeat must be finite and positive")
        for digest in (self.environment_digest, self.artifact_digest, self.runtime_identity_digest):
            if len(digest) != 64:
                raise ValueError("service contract digests must be SHA-256 hex")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ServiceProcessIdentity:
    """Stable process identity across nested PID namespaces.

    ``pid`` is the PID visible in the configured procfs.  ``control_pid`` is
    the optional PID understood by the current process namespace for signals
    and ``waitpid``-style bookkeeping.  On ordinary hosts they are identical
    and callers only need ``pid``.
    """

    pid: int
    start_identity: str
    process_group_id: int | None = None
    control_pid: int | None = None

    @property
    def execution_pid(self) -> int:
        return self.control_pid if self.control_pid is not None else self.pid


class ServiceContractDrift(RuntimeError):
    """Observed service runtime identity does not match the frozen launch contract."""


__all__ = ["ServiceContractDrift", "ServiceLaunchContract", "ServiceProcessIdentity"]
