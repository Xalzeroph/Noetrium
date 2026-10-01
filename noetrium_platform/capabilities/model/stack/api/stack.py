from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json

from noetrium_platform.foundation.kernel.kernel.durability import sha256_bytes
from noetrium_platform.foundation.kernel.kernel.identity import ImmutableModelIdentity


def _digest(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(raw)


@dataclass(frozen=True, slots=True)
class ModelArtifactClosure:
    """Exact model files that a serving stack is allowed to load."""

    weights_manifest_sha256: str
    tokenizer_sha256: str
    model_config_sha256: str
    model_code_sha256: str | None = None
    chat_template_sha256: str | None = None

    def __post_init__(self) -> None:
        for name in ("weights_manifest_sha256", "tokenizer_sha256", "model_config_sha256"):
            if not getattr(self, name):
                raise ValueError(f"model artifact closure missing {name}")

    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True, slots=True)
class RuntimeBuildIdentity:
    """Exact serving runtime identity, independent of mutable environment state."""

    container_digest: str
    engine_build_digest: str
    python_lock_digest: str
    cuda_runtime: str
    nccl_version: str
    torch_version: str
    kernel_extensions_digest: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not value:
                raise ValueError(f"runtime build identity missing {name}")

    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True, slots=True)
class ModelServingPolicy:
    """Engine-neutral serving semantics owned by the frozen model stack."""

    prefix_caching: bool | None = None
    prefix_cache_hash_algorithm: str | None = None
    chunked_prefill: bool | None = None
    max_batch_tokens: int | None = None
    runtime_tuning_revision: str = "legacy"

    def __post_init__(self) -> None:
        for name in ("prefix_caching", "chunked_prefill"):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise TypeError(f"model serving policy {name} must be bool or None")
        if self.prefix_cache_hash_algorithm is not None:
            if (
                type(self.prefix_cache_hash_algorithm) is not str
                or not self.prefix_cache_hash_algorithm.strip()
            ):
                raise ValueError(
                    "model serving policy prefix_cache_hash_algorithm must be text"
                )
            if self.prefix_caching is not True:
                raise ValueError(
                    "prefix_cache_hash_algorithm requires prefix_caching=True"
                )
        if (
            type(self.runtime_tuning_revision) is not str
            or not self.runtime_tuning_revision.strip()
        ):
            raise ValueError(
                "model serving policy runtime_tuning_revision must be non-empty text"
            )
        if self.max_batch_tokens is not None and (
            type(self.max_batch_tokens) is not int
            or self.max_batch_tokens <= 0
        ):
            raise ValueError(
                "model serving policy max_batch_tokens must be positive integer"
            )

    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True, slots=True)
class ModelStackSpec:
    """Immutable AI-infrastructure stack contract.

    Asset acquisition, Python environment lifecycle, process supervision, GPU
    observation and event publication remain owned by their own subsystems.
    """

    identity: ImmutableModelIdentity
    artifacts: ModelArtifactClosure
    runtime: RuntimeBuildIdentity
    tensor_parallel: int
    data_parallel: int
    expert_parallel: int
    pipeline_parallel: int
    reasoning_parser: str | None
    tool_call_parser: str | None
    kv_cache_dtype: str | None
    attention_backend: str | None
    scheduler_policy: str
    engine_args: tuple[str, ...] = ()
    serving_policy: ModelServingPolicy = field(default_factory=ModelServingPolicy)

    def __post_init__(self) -> None:
        for name in ("tensor_parallel", "data_parallel", "expert_parallel", "pipeline_parallel"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if not self.scheduler_policy:
            raise ValueError("scheduler_policy is required")

    def digest(self) -> str:
        return _digest({
            "identity": asdict(self.identity),
            "artifacts": asdict(self.artifacts),
            "runtime": asdict(self.runtime),
            "tensor_parallel": self.tensor_parallel,
            "data_parallel": self.data_parallel,
            "expert_parallel": self.expert_parallel,
            "pipeline_parallel": self.pipeline_parallel,
            "reasoning_parser": self.reasoning_parser,
            "tool_call_parser": self.tool_call_parser,
            "kv_cache_dtype": self.kv_cache_dtype,
            "attention_backend": self.attention_backend,
            "scheduler_policy": self.scheduler_policy,
            "engine_args": self.engine_args,
            "serving_policy": asdict(self.serving_policy),
        })


__all__ = [
    "ModelArtifactClosure",
    "ModelServingPolicy",
    "ModelStackSpec",
    "RuntimeBuildIdentity",
]
