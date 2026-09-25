from __future__ import annotations

from dataclasses import dataclass
import math

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.api import is_absolute_target_path


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

    ``pid`` is the logical target PID visible in the configured procfs.
    ``control_pid`` is the optional target PID understood by the current PID
    namespace. ``anchor_pid`` / ``anchor_start_identity`` identify an
    optional persistent ownership guardian. ``anchor_pid`` is procfs-visible
    and ``anchor_control_pid`` is the optional PID understood by the current
    namespace. The anchor outlives the target root until every forked descendant
    converges, so target exit never proves tree cleanup by itself.
    """

    pid: int
    start_identity: str
    process_group_id: int | None = None
    control_pid: int | None = None
    anchor_pid: int | None = None
    anchor_start_identity: str | None = None
    anchor_control_pid: int | None = None

    def __post_init__(self) -> None:
        if type(self.pid) is not int or self.pid <= 0:
            raise ValueError("service process pid must be positive")
        if type(self.start_identity) is not str or not self.start_identity:
            raise ValueError("service process start identity required")
        for name, value in (
            ("process_group_id", self.process_group_id),
            ("control_pid", self.control_pid),
            ("anchor_pid", self.anchor_pid),
            ("anchor_control_pid", self.anchor_control_pid),
        ):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"service process {name} must be positive or None")
        if (self.anchor_pid is None) != (self.anchor_start_identity is None):
            raise ValueError(
                "service process ownership anchor pid/start identity must be complete together"
            )
        if self.anchor_pid is None and self.anchor_control_pid is not None:
            raise ValueError(
                "service process anchor control pid requires an ownership anchor"
            )
        if self.anchor_start_identity is not None and (
            type(self.anchor_start_identity) is not str
            or not self.anchor_start_identity
        ):
            raise ValueError("service process ownership anchor start identity required")

    @property
    def execution_pid(self) -> int:
        return self.control_pid if self.control_pid is not None else self.pid

    @property
    def anchor_execution_pid(self) -> int | None:
        if self.anchor_pid is None:
            return None
        return (
            self.anchor_control_pid
            if self.anchor_control_pid is not None
            else self.anchor_pid
        )

    @property
    def ownership_pid(self) -> int:
        anchor = self.anchor_execution_pid
        return anchor if anchor is not None else self.execution_pid


class ServiceContractDrift(RuntimeError):
    """Observed service runtime identity does not match the frozen launch contract."""


__all__ = ["ServiceContractDrift", "ServiceLaunchContract", "ServiceProcessIdentity"]
