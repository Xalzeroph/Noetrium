from __future__ import annotations

from dataclasses import dataclass
import math
import re
import time

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from .heartbeat import ServiceHeartbeat
from .qualified_deployment import QualifiedDeploymentManifest


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _require_digest(value: str, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _require_digest_evidence_ref(value: str, field: str = "evidence_ref") -> str:
    if type(value) is not str or ":sha256:" not in value:
        raise ValueError(f"{field} must be a digest-bound evidence ref")
    kind, digest = value.split(":sha256:", 1)
    if not kind or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for char in kind):
        raise ValueError(f"{field} has invalid evidence kind")
    _require_digest(digest, f"{field} digest")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeQualificationReceipt:
    """Immutable proof that a live deployment still satisfies its frozen qualification."""

    deployment_id: str
    stack_digest: str
    qualification_certificate_digest: str
    heartbeat_qualification_digest: str
    qualified_roles: tuple[str, ...]
    process_pid: int
    process_start_marker: str
    argv_digest: str
    heartbeat_timestamp: float
    valid_until: float
    evidence_refs: tuple[str, ...]
    created_at: float
    def __post_init__(self) -> None:
        if not isinstance(self.deployment_id, str) or not self.deployment_id.strip():
            raise ValueError("runtime qualification deployment_id is required")
        _require_digest(self.stack_digest, "stack_digest")
        _require_digest(
            self.qualification_certificate_digest,
            "qualification_certificate_digest",
        )
        _require_digest(
            self.heartbeat_qualification_digest,
            "heartbeat_qualification_digest",
        )
        if self.heartbeat_qualification_digest != self.qualification_certificate_digest:
            raise ValueError("runtime qualification heartbeat/certificate digest drift")
        if not isinstance(self.qualified_roles, tuple) or not self.qualified_roles:
            raise TypeError("runtime qualification roles must be a non-empty tuple")
        if any(type(role) is not str or not role.strip() for role in self.qualified_roles):
            raise TypeError("runtime qualification roles must be non-empty strings")
        if len(set(self.qualified_roles)) != len(self.qualified_roles):
            raise ValueError("runtime qualification roles must be unique")
        if type(self.process_pid) is not int or self.process_pid <= 0:
            raise TypeError("runtime qualification process_pid must be a positive integer")
        if type(self.process_start_marker) is not str or not self.process_start_marker.strip():
            raise TypeError("runtime qualification process_start_marker is required")
        _require_digest(self.argv_digest, "argv_digest")
        for field, value in (("heartbeat_timestamp", self.heartbeat_timestamp), ("valid_until", self.valid_until)):
            if type(value) is not float or not math.isfinite(value) or value < 0:
                raise TypeError(f"runtime qualification {field} must be a finite non-negative float")
        if self.valid_until <= self.heartbeat_timestamp:
            raise ValueError("runtime qualification validity window is empty")
        if not isinstance(self.evidence_refs, tuple) or not self.evidence_refs:
            raise TypeError("runtime qualification evidence refs must be a non-empty tuple")
        try:
            for ref in self.evidence_refs:
                _require_digest_evidence_ref(ref)
        except ValueError as exc:
            raise TypeError("runtime qualification evidence refs must be digest-bound") from exc
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("runtime qualification evidence refs must be unique")
        heartbeat_refs = tuple(ref for ref in self.evidence_refs if ref.startswith("heartbeat:sha256:"))
        if len(heartbeat_refs) != 1:
            raise ValueError("runtime qualification requires exactly one heartbeat evidence ref")
        if type(self.created_at) is not float or not math.isfinite(self.created_at) or self.created_at < 0:
            raise TypeError("runtime qualification created_at must be a finite non-negative float")
        if not self.heartbeat_timestamp <= self.created_at <= self.valid_until:
            raise ValueError("runtime qualification creation time is outside heartbeat validity")

    def digest(self) -> str:
        return canonical_digest(self)


def _qualification_age_limit(value: float) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        raise TypeError("runtime qualification heartbeat age limit must be numeric")
    age_limit = float(value)
    if not math.isfinite(age_limit) or age_limit <= 0:
        raise ValueError("runtime qualification heartbeat age limit must be finite and positive")
    return age_limit


def _qualification_created_at(now: float | None, heartbeat: ServiceHeartbeat) -> float:
    created_at = time.time() if now is None else float(now)
    if not math.isfinite(created_at):
        raise ValueError("runtime qualification time must be finite")
    if heartbeat.timestamp > created_at:
        raise ValueError("runtime qualification heartbeat timestamp is in the future")
    return created_at


def _qualification_roles(
    deployment: QualifiedDeploymentManifest, required_roles: tuple[str, ...]
) -> tuple[str, ...]:
    allowed = set(deployment.certificate.qualified_roles)
    missing = set(required_roles) - allowed
    if missing:
        raise ValueError(f"runtime qualification certificate missing roles: {sorted(missing)}")
    return tuple(sorted(required_roles))


def _qualification_evidence_refs(
    heartbeat: ServiceHeartbeat, evidence_refs: tuple[str, ...]
) -> tuple[str, ...]:
    """Validate and canonicalize all caller evidence references.

    Algorithm-Complexity: O(N log N)
    Algorithm-Rationale: N is the caller evidence count; every extra digest-bound ref is validated and the final immutable evidence tuple is sorted for deterministic qualification identity.
    """
    expected_ref = (
        f"heartbeat:{heartbeat.deployment_id}:{heartbeat.pid}:"
        f"{heartbeat.process_start_marker}:{heartbeat.timestamp}"
    )
    if type(evidence_refs) is not tuple or expected_ref not in evidence_refs:
        raise ValueError("runtime qualification requires the exact live heartbeat evidence ref")
    extras = tuple(ref for ref in evidence_refs if ref != expected_ref)
    try:
        for ref in extras:
            _require_digest_evidence_ref(ref)
    except ValueError as exc:
        raise ValueError("runtime qualification extra evidence refs must be digest-bound") from exc
    if len(set(extras)) != len(extras):
        raise ValueError("runtime qualification extra evidence refs must be unique")
    if any(ref.startswith("heartbeat:sha256:") for ref in extras):
        raise ValueError("runtime qualification heartbeat evidence is owned by the live heartbeat")
    evidence_digest = canonical_digest(heartbeat)
    return (f"heartbeat:sha256:{evidence_digest}", *tuple(sorted(extras)))


def build_runtime_qualification_receipt(
    deployment: QualifiedDeploymentManifest,
    heartbeat: ServiceHeartbeat,
    *,
    required_roles: tuple[str, ...],
    evidence_refs: tuple[str, ...],
    max_heartbeat_age_seconds: float,
    now: float | None = None,
) -> RuntimeQualificationReceipt:
    """Validate live qualification against one exact frozen deployment."""

    age_limit = _qualification_age_limit(max_heartbeat_age_seconds)
    created_at = _qualification_created_at(now, heartbeat)
    if heartbeat.deployment_id != deployment.deployment_id:
        raise ValueError("runtime qualification heartbeat belongs to another deployment")
    stack_digest = deployment.stack.digest()
    if heartbeat.stack_digest != stack_digest:
        raise ValueError("runtime qualification stack digest drift")
    if not heartbeat.ready:
        raise ValueError("runtime qualification requires READY service")
    if heartbeat.age(created_at) > age_limit:
        raise ValueError("runtime qualification heartbeat is stale")

    certificate_digest = deployment.certificate.digest()
    if heartbeat.qualification_digest != certificate_digest:
        raise ValueError("live service qualification digest does not match frozen certificate")
    qualified_roles = _qualification_roles(deployment, required_roles)
    qualified_evidence = _qualification_evidence_refs(heartbeat, evidence_refs)
    return RuntimeQualificationReceipt(
        deployment_id=deployment.deployment_id,
        stack_digest=stack_digest,
        qualification_certificate_digest=certificate_digest,
        heartbeat_qualification_digest=heartbeat.qualification_digest,
        qualified_roles=qualified_roles,
        process_pid=heartbeat.pid,
        process_start_marker=heartbeat.process_start_marker,
        argv_digest=_require_digest(heartbeat.argv_digest, "heartbeat.argv_digest"),
        heartbeat_timestamp=float(heartbeat.timestamp),
        valid_until=float(heartbeat.timestamp) + age_limit,
        evidence_refs=qualified_evidence,
        created_at=float(created_at),
    )


__all__ = ["RuntimeQualificationReceipt", "build_runtime_qualification_receipt"]
