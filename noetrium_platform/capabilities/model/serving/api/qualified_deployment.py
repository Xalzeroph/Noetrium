from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math

from .placement import DeploymentPlacement
from noetrium_platform.capabilities.model.stack.api import ModelStackSpec


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _require_positive_finite(value: object, field: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise ValueError(f"resource envelope {field} must be finite and positive")


@dataclass(frozen=True, slots=True)
class ResourceEnvelope:
    peak_gpu_memory_bytes_per_device: int
    peak_host_memory_bytes: int
    max_qualified_concurrency: int
    ttft_p99_seconds: float
    tpot_p99_seconds: float
    minimum_output_tokens_per_second: float

    def __post_init__(self) -> None:
        if self.peak_gpu_memory_bytes_per_device <= 0 or self.peak_host_memory_bytes <= 0:
            raise ValueError("resource envelope requires measured positive memory peaks")
        if type(self.max_qualified_concurrency) is not int or self.max_qualified_concurrency <= 0:
            raise ValueError("qualified concurrency must be positive")
        _require_positive_finite(self.ttft_p99_seconds, "ttft_p99_seconds")
        _require_positive_finite(self.tpot_p99_seconds, "tpot_p99_seconds")
        _require_positive_finite(
            self.minimum_output_tokens_per_second,
            "minimum_output_tokens_per_second",
        )


@dataclass(frozen=True, slots=True)
class QualificationCertificate:
    model_stack_digest: str
    evidence_digest: str
    qualified_roles: tuple[str, ...]
    resource_envelope: ResourceEnvelope
    target_host_identity_digest: str

    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True, slots=True)
class RoleModelAssignment:
    role: str
    deployment_id: str


@dataclass(frozen=True, slots=True)
class RoleModelManifest:
    assignments: tuple[RoleModelAssignment, ...]

    def __post_init__(self) -> None:
        roles=[x.role for x in self.assignments]
        if len(roles)!=len(set(roles)):
            raise ValueError("each LLM role must have exactly one deployment; fallback lists are forbidden")
        if any(not x.deployment_id for x in self.assignments):
            raise ValueError("deployment_id is required")

    def deployment_for(self, role: str) -> str:
        matches=[x.deployment_id for x in self.assignments if x.role==role]
        if len(matches)!=1:
            raise KeyError(f"role has no frozen deployment assignment: {role}")
        return matches[0]

    def digest(self) -> str:
        return _digest([asdict(x) for x in sorted(self.assignments,key=lambda x:x.role)])


@dataclass(frozen=True, slots=True)
class QualifiedDeploymentManifest:
    deployment_id: str
    stack: ModelStackSpec
    certificate: QualificationCertificate
    placement: DeploymentPlacement
    host_identity_digest: str

    def __post_init__(self) -> None:
        if self.stack.digest()!=self.certificate.model_stack_digest:
            raise ValueError("qualification certificate does not match model stack")
        if self.certificate.target_host_identity_digest!=self.host_identity_digest:
            raise ValueError("qualification certificate is for a different host inventory")
        if len(self.placement.gpu_uuids)!=self.stack.tensor_parallel:
            raise ValueError("placement GPU count must match tensor parallel degree")

    def digest(self) -> str:
        payload={"deployment_id":self.deployment_id,"stack_digest":self.stack.digest(),"certificate_digest":self.certificate.digest(),"placement":asdict(self.placement),"host_identity_digest":self.host_identity_digest}
        return _digest(payload)
