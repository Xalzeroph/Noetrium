from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

from noetrium_platform.capabilities.model.asset.api import ModelAssetMode
from noetrium_platform.capabilities.model.asset.catalog import (
    PackagedModelSourceCatalog,
)
from noetrium_platform.capabilities.model.asset.runtime import ModelAssetManager
from noetrium_platform.capabilities.model.deployment.runtime.vllm_resources import (
    reconcile_vllm_compute_requirement,
)
from noetrium_platform.capabilities.model.stack.api import (
    MAX_VLLM_GPU_MEMORY_UTILIZATION,
    ModelServingPolicy,
    ModelStackSpec,
    RuntimeBuildIdentity,
)
from noetrium_platform.capabilities.model.stack.runtime import (
    ModelArtifactClosureAuthority,
)
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE, ScopeIdentity
from noetrium_platform.foundation.kernel.kernel import (
    ImmutableModelIdentity,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.kernel.durability import atomic_replace_bytes
from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandRunnerPort
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeRequirement,
    ComputeSchedulerPort,
    GpuSharingMode,
)


_GIB = 1024 ** 3
_VLLM_REPOSITORY = "vllm/vllm-openai"
_VLLM_RELEASE_SOURCE = _VLLM_REPOSITORY + ":v0.8.5"
_RUNTIME_FINGERPRINT_SCHEMA = "noetrium.docker-model-runtime-fingerprint.v1"
# Qualification starts with a deliberately narrow CUDA-graph scout surface.
# Larger qualification batches remain valid through vLLM eager fallback; the
# measured final admission capacity is then used to materialize and re-qualify
# the exact production graph surface.
_VLLM_SCOUT_CUDAGRAPH_CAPTURE_SIZES = (1, 2, 4, 8, 16, 32)
_VLLM_RELEASE_MAX_CUDAGRAPH_CAPTURE_SIZE = 512
_VLLM_RUNTIME_TUNING_REVISION = "vllm-0.8.5-adaptive-cudagraph-v1"


def vllm_cudagraph_capture_sizes_for_capacity(
    max_concurrency: int,
    *,
    preferred_concurrency: int | None = None,
) -> tuple[int, ...]:
    """Minimal logarithmic graph surface for one measured admission envelope.

    vLLM 0.8.5 can run batches above the largest captured graph eagerly. Keep
    powers of two for bounded padding, add the measured throughput knee, and
    terminate exactly at the qualified capacity up to vLLM's own V1 default
    graph ceiling. This avoids capturing graph shapes that production admission
    can never select.
    """

    if type(max_concurrency) is not int or max_concurrency <= 0:
        raise ValueError("vLLM cudagraph capacity must be positive")
    if preferred_concurrency is not None and (
        type(preferred_concurrency) is not int
        or preferred_concurrency <= 0
        or preferred_concurrency > max_concurrency
    ):
        raise ValueError(
            "vLLM preferred cudagraph concurrency must be positive and within capacity"
        )
    ceiling = min(max_concurrency, _VLLM_RELEASE_MAX_CUDAGRAPH_CAPTURE_SIZE)
    sizes: set[int] = set()
    value = 1
    while value <= ceiling:
        sizes.add(value)
        value *= 2
    sizes.add(ceiling)
    if preferred_concurrency is not None and preferred_concurrency <= ceiling:
        sizes.add(preferred_concurrency)
    return tuple(sorted(sizes))


def _vllm_compilation_config(capture_sizes: tuple[int, ...]) -> str:
    if not capture_sizes or any(type(value) is not int or value <= 0 for value in capture_sizes):
        raise ValueError("vLLM cudagraph capture sizes must be positive integers")
    return json.dumps(
        {"cudagraph_capture_sizes": capture_sizes},
        sort_keys=True,
        separators=(",", ":"),
    )


_VLLM_SCOUT_COMPILATION_CONFIG = _vllm_compilation_config(
    _VLLM_SCOUT_CUDAGRAPH_CAPTURE_SIZES
)
_VLLM_PLATFORM_ENGINE_ARGS = (
    "--disable-uvicorn-access-log",
    "--generation-config",
    "vllm",
    "--compilation-config",
    _VLLM_SCOUT_COMPILATION_CONFIG,
)


_DTYPE_BYTES = {
    "float64": 8,
    "double": 8,
    "float32": 4,
    "float": 4,
    "bfloat16": 2,
    "bf16": 2,
    "float16": 2,
    "fp16": 2,
    "half": 2,
    "float8": 1,
    "fp8": 1,
    "float8_e4m3fn": 1,
    "float8_e5m2": 1,
}
_KV_CACHE_FRAGMENTATION_NUMERATOR = 9
_KV_CACHE_FRAGMENTATION_DENOMINATOR = 8
# vLLM reserves weights, KV cache and non-KV engine workspace inside the same
# per-device memory target. Compilation/cudagraph/allocator workspace is material
# for modern transformer servers, so keep a conservative non-KV reserve; when a
# shared device cannot satisfy it, topology search expands tensor parallelism
# instead of oversubscribing the device.
_MODEL_RUNTIME_HEADROOM_FRACTION = 0.25
_MIN_MODEL_RUNTIME_HEADROOM_BYTES = 4 * _GIB
_MIN_KV_CACHE_BYTES = 1024 ** 3


def _positive_int(document: dict[str, object], *keys: str) -> int | None:
    for key in keys:
        value = document.get(key)
        if type(value) is int and value > 0:
            return value
    return None


def _model_text_config(asset_path: Path) -> dict[str, object]:
    path = asset_path / "config.json"
    try:
        document = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("model runtime memory planning requires valid config.json") from exc
    if not isinstance(document, dict):
        raise RuntimeError("model runtime memory planning requires object config.json")
    nested = document.get("text_config")
    if isinstance(nested, dict):
        return {**document, **nested}
    return document


def _tensor_parallel_supported_by_model_geometry(
    asset_path: Path,
    tensor_parallel: int,
) -> bool:
    if type(tensor_parallel) is not int or tensor_parallel <= 0:
        raise ValueError("model tensor parallelism must be positive integer")
    document = _model_text_config(asset_path)
    attention_heads = _positive_int(
        document,
        "num_attention_heads",
        "n_head",
        "num_heads",
    )
    if attention_heads is None:
        raise RuntimeError(
            "model config lacks attention-head geometry for tensor parallel planning"
        )
    return attention_heads % tensor_parallel == 0


def _tensor_parallel_candidates_for_model_geometry(
    asset_path: Path,
) -> tuple[int, ...]:
    """Enumerate every legal TP factor from immutable model geometry.

    Physical GPU count/memory/pressure remains ComputeScheduler authority; this
    function only removes the old host-specific TP ceiling from model planning.
    """

    document = _model_text_config(asset_path)
    attention_heads = _positive_int(
        document,
        "num_attention_heads",
        "n_head",
        "num_heads",
    )
    if attention_heads is None:
        raise RuntimeError(
            "model config lacks attention-head geometry for tensor parallel planning"
        )
    return tuple(
        factor
        for factor in range(1, attention_heads + 1)
        if attention_heads % factor == 0
    )


def model_kv_cache_bytes_per_token(
    asset_path: Path,
    *,
    dtype: str,
    tensor_parallel: int,
) -> int:
    """Exact per-device KV bytes for one token under the canonical model geometry."""
    if tensor_parallel <= 0:
        raise ValueError("KV cache planning requires positive tensor parallelism")
    document = _model_text_config(asset_path)
    layers = _positive_int(document, "num_hidden_layers", "n_layer", "num_layers")
    attention_heads = _positive_int(
        document,
        "num_attention_heads",
        "n_head",
        "num_heads",
    )
    kv_heads = _positive_int(
        document,
        "num_key_value_heads",
        "multi_query_group_num",
    )
    hidden_size = _positive_int(document, "hidden_size", "n_embd", "d_model")
    head_dim = _positive_int(document, "head_dim")
    if attention_heads is None:
        raise RuntimeError("model config lacks attention-head geometry for KV planning")
    if kv_heads is None:
        kv_heads = attention_heads
    if head_dim is None:
        if hidden_size is None or hidden_size % attention_heads:
            raise RuntimeError("model config lacks exact attention head dimension")
        head_dim = hidden_size // attention_heads
    if layers is None:
        raise RuntimeError("model config lacks layer count for KV planning")
    dtype_bytes = _DTYPE_BYTES.get(dtype.strip().lower())
    if dtype_bytes is None:
        raise RuntimeError("unsupported model dtype for KV memory planning: " + dtype)
    kv_partitions = min(tensor_parallel, kv_heads)
    per_device_kv_heads = math.ceil(kv_heads / kv_partitions)
    raw = (
        layers
        * per_device_kv_heads
        * head_dim
        * 2
        * dtype_bytes
    )
    return max(
        1,
        math.ceil(
            raw
            * _KV_CACHE_FRAGMENTATION_NUMERATOR
            / _KV_CACHE_FRAGMENTATION_DENOMINATOR
        ),
    )


def model_kv_cache_budget_bytes(
    asset_path: Path,
    *,
    context_length: int,
    dtype: str,
    tensor_parallel: int,
) -> int:
    """Canonical per-device KV budget for one full-context sequence."""
    if context_length <= 0:
        raise ValueError("KV cache planning requires positive context length")
    per_token = model_kv_cache_bytes_per_token(
        asset_path,
        dtype=dtype,
        tensor_parallel=tensor_parallel,
    )
    return max(_MIN_KV_CACHE_BYTES, per_token * context_length)


def _kv_cache_budget_bytes(
    asset_path: Path,
    *,
    context_length: int,
    dtype: str,
    tensor_parallel: int,
) -> int:
    return model_kv_cache_budget_bytes(
        asset_path,
        context_length=context_length,
        dtype=dtype,
        tensor_parallel=tensor_parallel,
    )


def _model_runtime_vram_budget_bytes(
    asset_path: Path,
    *,
    total_asset_bytes: int,
    context_length: int,
    dtype: str,
    tensor_parallel: int,
) -> int:
    if total_asset_bytes <= 0:
        raise ValueError("model runtime memory planning requires positive asset bytes")
    per_device_weights = max(
        1,
        math.ceil(total_asset_bytes / tensor_parallel),
    )
    kv_cache = _kv_cache_budget_bytes(
        asset_path,
        context_length=context_length,
        dtype=dtype,
        tensor_parallel=tensor_parallel,
    )
    runtime_headroom = max(
        _MIN_MODEL_RUNTIME_HEADROOM_BYTES,
        math.ceil(per_device_weights * _MODEL_RUNTIME_HEADROOM_FRACTION),
    )
    return per_device_weights + kv_cache + runtime_headroom


def _model_compute_requirement(
    asset_path: Path,
    *,
    total_asset_bytes: int,
    context_length: int,
    dtype: str,
    tensor_parallel: int,
) -> ComputeRequirement:
    """Freeze hard model capacity while keeping shared-GPU load as a preference.

    VRAM residual capacity is admission-critical and durably reserved. Instantaneous
    GPU utilization is intentionally not a hard cutoff for shared serving because
    candidate discovery and allocation observe at different instants; a fixed
    utilization ceiling would turn harmless load jitter into placement TOCTOU.
    The compute scheduler still ranks lower-utilization devices first.
    """

    required_free = _model_runtime_vram_budget_bytes(
        asset_path,
        total_asset_bytes=total_asset_bytes,
        context_length=context_length,
        dtype=dtype,
        tensor_parallel=tensor_parallel,
    )
    return ComputeRequirement(
        cpu_cores=4,
        memory_bytes=max(4 * _GIB, min(total_asset_bytes, 16 * _GIB)),
        gpu_count=tensor_parallel,
        required_gpu_free_memory_bytes=required_free,
        gpu_admission_headroom_fraction=1.0 - MAX_VLLM_GPU_MEMORY_UTILIZATION,
        gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
    )


@dataclass(frozen=True, slots=True)
class MaterializedModelStack:
    stack: ModelStackSpec
    compute: ComputeRequirement
    image_source: str
    fingerprint_ref: str

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "stack_digest": self.stack.digest(),
                "compute": self.compute,
                "image_source": self.image_source,
                "fingerprint_ref": self.fingerprint_ref,
            }
        )


class ModelStackPlacementUnavailable(RuntimeError):
    """No currently admissible compute topology can host a model stack."""



class DockerModelStackMaterializer:
    """Freeze model bytes + immutable OCI runtime into one executable stack.

    Mutable image tags are acquisition hints only. The returned ModelStackSpec
    always carries the exact Docker image ID digest and a fingerprint collected
    from that immutable image.
    """

    def __init__(
        self,
        *,
        assets: ModelAssetManager,
        compute_scheduler: ComputeSchedulerPort,
        command_runner: LocalCommandRunnerPort,
        state_root: Path,
        docker_executable: str = "docker",
        source_catalog: PackagedModelSourceCatalog | None = None,
        vllm_default_source: str = _VLLM_RELEASE_SOURCE,
        image_pull_timeout_seconds: float = 3600.0,
        fingerprint_timeout_seconds: float = 600.0,
    ) -> None:
        if not isinstance(assets, ModelAssetManager):
            raise TypeError("model stack materializer requires ModelAssetManager")
        if not callable(getattr(compute_scheduler, "candidates", None)):
            raise TypeError("model stack materializer requires compute candidates()")
        if not callable(getattr(command_runner, "run", None)):
            raise TypeError("model stack materializer requires command run()")
        if not isinstance(state_root, Path):
            raise TypeError("model stack materializer state_root must be pathlib.Path")
        if not docker_executable.strip() or not vllm_default_source.strip():
            raise ValueError("Docker model runtime source identity is required")
        self._assets = assets
        self._sources = source_catalog or PackagedModelSourceCatalog()
        self._compute = compute_scheduler
        self._runner = command_runner
        self._root = state_root / "model-runtime-fingerprints"
        self._root.mkdir(parents=True, exist_ok=True)
        self._docker = docker_executable
        self._vllm_default = vllm_default_source
        self._pull_timeout = float(image_pull_timeout_seconds)
        self._fingerprint_timeout = float(fingerprint_timeout_seconds)

    def _image_id(self, source: str) -> str | None:
        result = self._runner.run(
            (
                self._docker,
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                source,
            ),
            timeout_seconds=30.0,
        )
        if result.returncode != 0:
            return None
        value = result.stdout.strip()
        if not value.startswith("sha256:"):
            raise RuntimeError("Docker image inspect returned non-SHA256 identity")
        digest = value[7:]
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise RuntimeError("Docker image inspect returned invalid SHA256 identity")
        return digest

    def _resolve_vllm_image(self) -> tuple[str, str]:
        # Model-runtime source is a platform release decision. Never scan the
        # host for a "highest" local vLLM tag: unrelated cached images must not
        # mutate the research runtime generation. Reuse the exact release tag
        # when present; otherwise materialize exactly that release.
        source = self._vllm_default
        digest = self._image_id(source)
        if digest is None:
            pulled = self._runner.run(
                (self._docker, "pull", source),
                timeout_seconds=self._pull_timeout,
            )
            if pulled.returncode != 0:
                raise RuntimeError(
                    "Docker model runtime acquisition failed: " + source
                )
            digest = self._image_id(source)
        if digest is None:
            raise RuntimeError(
                "Docker model runtime acquisition did not materialize an image"
            )
        return source, digest

    @staticmethod
    def _fingerprint_script(engine: str) -> str:
        return r"""
import hashlib, importlib.metadata as md, json, pathlib, sys
import torch
engine = __import__("sys").argv[1]
engine_version = md.version(engine)
rows=[]
for d in sorted(md.distributions(), key=lambda x: (x.metadata.get("Name") or "").lower()):
    name=(d.metadata.get("Name") or "").strip()
    if name:
        rows.append(f"{name}=={d.version}")
python_lock=hashlib.sha256("\n".join(rows).encode()).hexdigest()
roots=[]
for mod in (engine,"torch"):
    try:
        m=__import__(mod)
        roots.append((mod,pathlib.Path(m.__file__).resolve().parent))
    except Exception:
        pass
ext=[]
for mod,root in roots:
    for p in root.rglob("*.so"):
        if p.is_file():
            h=hashlib.sha256()
            with p.open("rb") as f:
                for chunk in iter(lambda:f.read(1024*1024),b""):
                    h.update(chunk)
            ext.append((mod,str(p.relative_to(root)),h.hexdigest(),p.stat().st_size))
extensions=hashlib.sha256(json.dumps(sorted(ext),separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
exe=pathlib.Path("/usr/local/bin/"+engine)
engine_executable=(hashlib.sha256(exe.read_bytes()).hexdigest() if exe.is_file() else hashlib.sha256(engine_version.encode()).hexdigest())
try:
    nccl=torch.cuda.nccl.version()
    if isinstance(nccl,tuple):
        nccl=".".join(map(str,nccl))
    else:
        nccl=str(nccl)
except Exception:
    nccl="unavailable"
print(json.dumps({
  "engine":engine,
  "engine_version":engine_version,
  "engine_executable_sha256":engine_executable,
  "python_version":sys.version.split()[0],
  "python_lock_digest":python_lock,
  "torch_version":torch.__version__,
  "cuda_runtime":str(torch.version.cuda or "unavailable"),
  "nccl_version":nccl,
  "kernel_extensions_digest":extensions,
},sort_keys=True,separators=(",",":")))
"""

    def _runtime_fingerprint(
        self,
        *,
        engine: str,
        image_digest: str,
    ) -> dict[str, str]:
        path = self._root / f"{image_digest}.json"
        if path.is_file():
            try:
                value = json.loads(path.read_text("utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                value = None
            if (
                isinstance(value, dict)
                and value.get("schema") == _RUNTIME_FINGERPRINT_SCHEMA
                and value.get("image_digest") == image_digest
                and value.get("engine") == engine
            ):
                return {str(k): str(v) for k, v in value.items()}

        result = self._runner.run(
            (
                self._docker,
                "run",
                "--rm",
                "--entrypoint",
                "python3",
                f"sha256:{image_digest}",
                "-c",
                self._fingerprint_script(engine),
                engine,
            ),
            timeout_seconds=self._fingerprint_timeout,
        )
        if result.returncode != 0:
            raise RuntimeError("Docker model runtime fingerprint probe failed")
        lines = tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
        if not lines:
            raise RuntimeError("Docker model runtime fingerprint probe returned no output")
        try:
            observed = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Docker model runtime fingerprint probe returned invalid JSON"
            ) from exc
        required = (
            "engine",
            "engine_version",
            "engine_executable_sha256",
            "python_version",
            "python_lock_digest",
            "torch_version",
            "cuda_runtime",
            "nccl_version",
            "kernel_extensions_digest",
        )
        if not isinstance(observed, dict) or any(
            type(observed.get(key)) is not str or not observed[key]
            for key in required
        ):
            raise RuntimeError("Docker model runtime fingerprint is incomplete")
        payload = {
            "schema": _RUNTIME_FINGERPRINT_SCHEMA,
            "image_digest": image_digest,
            **{key: observed[key] for key in required},
        }
        atomic_replace_bytes(
            path,
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        return payload

    def _ensure_asset(
        self,
        model_id: str,
        *,
        scope: ScopeIdentity | None,
    ):
        asset = None
        try:
            asset = self._assets.model(model_id)
        except (FileNotFoundError, KeyError):
            pass
        if asset is not None and asset.path.exists():
            return asset

        entry = self._sources.resolve(model_id)
        resolved_scope = PLATFORM_SCOPE if scope is None else scope
        if asset is None:
            return self._assets.fetch_model(
                model_id,
                resolved_scope,
                entry.source,
                family=entry.family,
                tags=entry.tags,
            )

        usage = self._assets.model_usage(model_id)
        if usage.deployment_ids or usage.desired_running_deployment_ids:
            raise RuntimeError(
                "inaccessible model asset retains deployment references: "
                + model_id
            )
        if asset.mode is ModelAssetMode.REFERENCE:
            return self._assets.materialize_reference_from_source(
                model_id,
                resolved_scope,
                entry.source,
                family=entry.family,
                tags=entry.tags,
            )
        raise RuntimeError(
            "inaccessible managed model asset requires explicit recovery: "
            + model_id
        )

    def _candidate(
        self,
        *,
        model_id: str,
        scope: ScopeIdentity,
        tensor_parallel: int,
        image_digest: str,
        image_source: str,
        fingerprint: dict[str, str],
        gpu_memory_utilization: float | None = None,
    ) -> MaterializedModelStack:
        asset = self._assets.model(model_id)
        config = self._assets.model_config(model_id)
        stats = self._assets.model_stats(model_id)
        if config is None:
            raise RuntimeError(
                f"model stack materialization requires config.json: {model_id}"
            )
        if not config.torch_dtype or not config.max_position_embeddings:
            raise RuntimeError(
                f"model config lacks dtype/context identity: {model_id}"
            )
        artifacts = ModelArtifactClosureAuthority().freeze(asset.path)
        quantization = config.quantization_method
        revision = "artifact-sha256:" + artifacts.digest()
        identity = ImmutableModelIdentity(
            logical_name=model_id,
            model_id=model_id,
            revision=revision,
            engine="vllm",
            engine_version=fingerprint["engine_version"],
            dtype=config.torch_dtype,
            quantization=quantization,
            context_length=config.max_position_embeddings,
            tokenizer_revision="sha256:" + artifacts.tokenizer_sha256,
        )
        runtime = RuntimeBuildIdentity(
            container_digest=image_digest,
            engine_build_digest=canonical_digest(
                {
                    "engine": "vllm",
                    "engine_version": fingerprint["engine_version"],
                    "executable_sha256": fingerprint["engine_executable_sha256"],
                    "image_digest": image_digest,
                }
            ),
            python_lock_digest=fingerprint["python_lock_digest"],
            cuda_runtime=fingerprint["cuda_runtime"],
            nccl_version=fingerprint["nccl_version"],
            torch_version=fingerprint["torch_version"],
            kernel_extensions_digest=fingerprint["kernel_extensions_digest"],
        )
        stack = ModelStackSpec(
            identity=identity,
            artifacts=artifacts,
            runtime=runtime,
            tensor_parallel=tensor_parallel,
            data_parallel=1,
            expert_parallel=1,
            pipeline_parallel=1,
            reasoning_parser=None,
            tool_call_parser=None,
            kv_cache_dtype=None,
            attention_backend=None,
            scheduler_policy="default",
            engine_args=(
                _VLLM_PLATFORM_ENGINE_ARGS
                + (
                    ()
                    if gpu_memory_utilization is None
                    else (
                        "--gpu-memory-utilization",
                        (
                            f"{gpu_memory_utilization:.6f}"
                            .rstrip("0")
                            .rstrip(".")
                        ),
                    )
                )
            ),
            serving_policy=ModelServingPolicy(
                prefix_caching=True,
                chunked_prefill=True,
                runtime_tuning_revision=_VLLM_RUNTIME_TUNING_REVISION,
            ),
        )
        base = _model_compute_requirement(
            asset.path,
            total_asset_bytes=stats.bytes,
            context_length=config.max_position_embeddings,
            dtype=config.torch_dtype,
            tensor_parallel=tensor_parallel,
        )
        compute = reconcile_vllm_compute_requirement(stack, base)
        return MaterializedModelStack(
            stack=stack,
            compute=compute,
            image_source=image_source,
            fingerprint_ref=(
                "docker-image:sha256:"
                + image_digest
                + ":fingerprint:"
                + canonical_digest(fingerprint)
            ),
        )

    def _source_context(
        self,
        model_id: str,
        *,
        scope: ScopeIdentity | None,
    ) -> tuple[ScopeIdentity, str, str, dict[str, str]]:
        asset = self._ensure_asset(model_id, scope=scope)
        holder_scope = asset.scope if scope is None else scope
        source, image_digest = self._resolve_vllm_image()
        fingerprint = self._runtime_fingerprint(
            engine="vllm",
            image_digest=image_digest,
        )
        return holder_scope, source, image_digest, fingerprint

    def materialize_for_tensor_parallel(
        self,
        model_id: str,
        tensor_parallel: int,
        *,
        scope: ScopeIdentity | None = None,
    ) -> MaterializedModelStack:
        if type(tensor_parallel) is not int or tensor_parallel <= 0:
            raise ValueError("model tensor parallelism must be positive")
        holder_scope, source, image_digest, fingerprint = self._source_context(
            model_id,
            scope=scope,
        )
        asset = self._assets.model(model_id)
        if not _tensor_parallel_supported_by_model_geometry(
            asset.path,
            tensor_parallel,
        ):
            raise ValueError(
                "model tensor parallelism is incompatible with attention-head geometry: "
                f"{model_id}:tp={tensor_parallel}"
            )
        return self._candidate(
            model_id=model_id,
            scope=holder_scope,
            tensor_parallel=tensor_parallel,
            image_digest=image_digest,
            image_source=source,
            fingerprint=fingerprint,
        )

    def materialize(
        self,
        model_id: str,
        *,
        scope: ScopeIdentity | None = None,
    ) -> MaterializedModelStack:
        holder_scope, source, image_digest, fingerprint = self._source_context(
            model_id,
            scope=scope,
        )
        asset = self._assets.model(model_id)
        for tensor_parallel in _tensor_parallel_candidates_for_model_geometry(
            asset.path
        ):
            provisional = self._candidate(
                model_id=model_id,
                scope=holder_scope,
                tensor_parallel=tensor_parallel,
                image_digest=image_digest,
                image_source=source,
                fingerprint=fingerprint,
            )
            if self._compute.candidates(
                provisional.compute,
                scope=holder_scope,
            ):
                return provisional
        raise ModelStackPlacementUnavailable(
            "no compute topology can materialize model stack: " + model_id
        )


__all__ = [
    "DockerModelStackMaterializer",
    "MaterializedModelStack",
    "ModelStackPlacementUnavailable",
    "model_kv_cache_budget_bytes",
    "model_kv_cache_bytes_per_token",
    "vllm_cudagraph_capture_sizes_for_capacity",
]
