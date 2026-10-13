from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math

from .placement import DeploymentPlacement
from .deployment import (
    FrozenDeploymentIdentity,
    FrozenDeploymentSet,
    FrozenRoleAssignment,
)
from noetrium_platform.capabilities.model.stack.api import (
    FrozenModelStack,
    parse_vllm_engine_resource_args,
)


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
    latency_isolation_concurrency: int
    preemptive_latency_isolation: bool
    preemptive_return_ttft_p99_seconds: float | None
    preemptive_return_tpot_p99_seconds: float | None
    ttft_p99_seconds: float
    tpot_p99_seconds: float
    minimum_output_tokens_per_second: float
    max_prefill_queued_tokens: int
    prefill_input_tokens_per_second: float
    preferred_operating_concurrency: int | None = None

    def __post_init__(self) -> None:
        if self.peak_gpu_memory_bytes_per_device <= 0 or self.peak_host_memory_bytes <= 0:
            raise ValueError("resource envelope requires measured positive memory peaks")
        if type(self.max_qualified_concurrency) is not int or self.max_qualified_concurrency <= 0:
            raise ValueError("qualified concurrency must be positive")
        if (
            type(self.latency_isolation_concurrency) is not int
            or self.latency_isolation_concurrency <= 0
            or self.latency_isolation_concurrency > self.max_qualified_concurrency
        ):
            raise ValueError(
                "latency isolation concurrency must be positive and cannot "
                "exceed qualified concurrency"
            )
        if type(self.preemptive_latency_isolation) is not bool:
            raise TypeError(
                "preemptive latency isolation capability must be bool"
            )
        return_metrics = (
            self.preemptive_return_ttft_p99_seconds,
            self.preemptive_return_tpot_p99_seconds,
        )
        if (return_metrics[0] is None) != (return_metrics[1] is None):
            raise ValueError(
                "preemptive return TTFT/TPOT measurements must be both present or absent"
            )
        if return_metrics[0] is not None:
            _require_positive_finite(
                return_metrics[0],
                "preemptive_return_ttft_p99_seconds",
            )
            _require_positive_finite(
                return_metrics[1],
                "preemptive_return_tpot_p99_seconds",
            )
        if self.preemptive_latency_isolation and return_metrics[0] is None:
            raise ValueError(
                "preemptive latency isolation requires measured return latency"
            )
        preferred = self.preferred_operating_concurrency
        if preferred is None:
            preferred = self.max_qualified_concurrency
            object.__setattr__(
                self,
                "preferred_operating_concurrency",
                preferred,
            )
        if (
            type(preferred) is not int
            or preferred <= 0
            or preferred > self.max_qualified_concurrency
        ):
            raise ValueError(
                "preferred operating concurrency must be positive and "
                "cannot exceed qualified concurrency"
            )
        _require_positive_finite(self.ttft_p99_seconds, "ttft_p99_seconds")
        _require_positive_finite(self.tpot_p99_seconds, "tpot_p99_seconds")
        _require_positive_finite(
            self.minimum_output_tokens_per_second,
            "minimum_output_tokens_per_second",
        )
        _require_positive_finite(
            self.prefill_input_tokens_per_second,
            "prefill_input_tokens_per_second",
        )
        if (
            type(self.max_prefill_queued_tokens) is not int
            or self.max_prefill_queued_tokens <= 0
        ):
            raise ValueError(
                "resource envelope max_prefill_queued_tokens must be positive"
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
    capability_id: str
    input_schema_id: str
    output_schema_id: str
    deployment_id: str

    def __post_init__(self) -> None:
        for name in ("role", "capability_id", "input_schema_id", "output_schema_id", "deployment_id"):
            value=getattr(self,name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"model assignment {name} is required")

    @property
    def protocol_key(self) -> tuple[str, str, str, str]:
        return (self.role,self.capability_id,self.input_schema_id,self.output_schema_id)


@dataclass(frozen=True, slots=True)
class RoleModelManifest:
    assignments: tuple[RoleModelAssignment, ...]

    def __post_init__(self) -> None:
        keys=[x.protocol_key for x in self.assignments]
        if len(keys)!=len(set(keys)):
            raise ValueError("each model role/capability protocol must have exactly one deployment")
        if not self.assignments:
            raise ValueError("model manifest requires at least one capability assignment")

    def deployment_for(
        self,
        role: str,
        capability_id: str,
        input_schema_id: str,
        output_schema_id: str,
    ) -> str:
        key=(role,capability_id,input_schema_id,output_schema_id)
        matches=[x.deployment_id for x in self.assignments if x.protocol_key==key]
        if len(matches)!=1:
            raise KeyError(f"model capability has no frozen deployment assignment: {key}")
        return matches[0]

    def digest(self) -> str:
        return _digest([
            asdict(x)
            for x in sorted(self.assignments,key=lambda x:x.protocol_key)
        ])


@dataclass(frozen=True, slots=True)
class QualifiedDeploymentManifest:
    deployment_id: str
    stack: FrozenModelStack
    certificate: QualificationCertificate
    placement: DeploymentPlacement
    host_identity_digest: str

    def __post_init__(self) -> None:
        if self.stack.digest()!=self.certificate.model_stack_digest:
            raise ValueError("qualification certificate does not match model stack")
        if self.certificate.target_host_identity_digest!=self.host_identity_digest:
            raise ValueError("qualification certificate is for a different host inventory")
        if self.stack.identity.engine.lower() == "vllm":
            if self.stack.data_parallel != 1:
                raise ValueError(
                    "qualified vLLM internal data parallel requires an auxiliary "
                    "RPC endpoint with exact resource authority"
                )
            expected_gpu_count = (
                self.stack.tensor_parallel * self.stack.pipeline_parallel
            )
        else:
            expected_gpu_count = self.stack.tensor_parallel
        if len(self.placement.gpu_uuids) != expected_gpu_count:
            raise ValueError(
                "placement GPU count does not match frozen engine topology"
            )
        if self.stack.identity.engine.lower() == "vllm":
            intent = parse_vllm_engine_resource_args(self.stack.engine_args)
            qualified = self.certificate.resource_envelope.max_qualified_concurrency
            active_limit = (
                intent.max_num_seqs
                if intent.max_num_active_seqs is None
                else intent.max_num_active_seqs
            )
            queue_limit = intent.max_num_queued_requests
            if active_limit is not None and qualified > active_limit:
                raise ValueError(
                    "qualified concurrency exceeds frozen vLLM active "
                    "sequence admission limit"
                )
            if queue_limit is not None and qualified > queue_limit:
                raise ValueError(
                    "qualified concurrency exceeds frozen vLLM "
                    "max-num-queued-reqs"
                )

    def digest(self) -> str:
        payload={"deployment_id":self.deployment_id,"stack_digest":self.stack.digest(),"certificate_digest":self.certificate.digest(),"placement":asdict(self.placement),"host_identity_digest":self.host_identity_digest}
        return _digest(payload)

def freeze_model_deployment(
    deployment: QualifiedDeploymentManifest,
) -> FrozenDeploymentIdentity:
    if not isinstance(deployment, QualifiedDeploymentManifest):
        raise TypeError(
            "freeze_model_deployment requires QualifiedDeploymentManifest"
        )
    return FrozenDeploymentIdentity(
        deployment_id=deployment.deployment_id,
        deployment_digest=deployment.digest(),
        stack_digest=deployment.stack.digest(),
        artifact_digest=deployment.stack.artifacts.digest(),
        runtime_identity_digest=deployment.stack.runtime.digest(),
        qualification_certificate_digest=deployment.certificate.digest(),
        host_identity_digest=deployment.host_identity_digest,
        gpu_uuids=deployment.placement.gpu_uuids,
    )


def freeze_model_deployment_set(
    role_manifest: RoleModelManifest,
    deployments: tuple[QualifiedDeploymentManifest, ...],
) -> FrozenDeploymentSet:
    if not isinstance(role_manifest, RoleModelManifest):
        raise TypeError(
            "freeze_model_deployment_set requires RoleModelManifest"
        )
    if type(deployments) is not tuple or any(
        not isinstance(item, QualifiedDeploymentManifest)
        for item in deployments
    ):
        raise TypeError(
            "freeze_model_deployment_set requires qualified deployment tuple"
        )
    return FrozenDeploymentSet(
        role_manifest_digest=role_manifest.digest(),
        assignments=tuple(
            FrozenRoleAssignment(
                item.role,
                item.capability_id,
                item.input_schema_id,
                item.output_schema_id,
                item.deployment_id,
            )
            for item in role_manifest.assignments
        ),
        deployments=tuple(
            freeze_model_deployment(item) for item in deployments
        ),
    )
