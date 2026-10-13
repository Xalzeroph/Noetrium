from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
from threading import Lock

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
    parse_vllm_engine_resource_args,
    ModelServingPolicy,
    FrozenModelStack,
    RuntimeBuildIdentity,
)
from noetrium_platform.capabilities.model.stack.runtime import (
    ModelArtifactClosureAuthority,
)
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE, NoetriumUnit, scope_key
from noetrium_platform.foundation.kernel.kernel import (
    ImmutableModelIdentity,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.kernel import atomic_replace_bytes
from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandRunnerPort
from noetrium_platform.infrastructure.resources.authority import (
    AuthoritySnapshot,
    UniversalResourceAuthority,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeInventoryPort,
    ComputePlacementUnavailable,
    ComputeRequirement,
    GpuRuntimeObserverPort,
    GpuRuntimeSnapshot,
    GpuSharingMode,
    HostRuntimeObserverPort,
    HostRuntimeSnapshot,
)
from noetrium_platform.infrastructure.resources.compute.placement import (
    compute_claim_candidates,
)


_GIB = 1024 ** 3
_VLLM_REPOSITORY = "vllm/vllm-openai"
_VLLM_RELEASE_SOURCE = _VLLM_REPOSITORY + ":v0.8.5"
_VLLM_PATCH_REVISION = "explicit-authority-kv-v2"
_VLLM_PATCHED_SOURCE = "noetrium/vllm-openai:v0.8.5-" + _VLLM_PATCH_REVISION
_RUNTIME_FINGERPRINT_SCHEMA = "noetrium.docker-model-runtime-fingerprint.v1"
# Qualification starts with a deliberately narrow CUDA-graph scout surface.
# Larger qualification and production batches remain valid through vLLM eager
# fallback; admission tuning must not silently enlarge this boot-proven graph
# memory surface.
_VLLM_SCOUT_CUDAGRAPH_CAPTURE_SIZES = (1, 2, 4, 8, 16, 32)
_VLLM_RUNTIME_TUNING_REVISION = "vllm-0.8.5-adaptive-cudagraph-v1"


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
_MIB = 1024 ** 2


def _cpu_offload_bytes_to_engine_args(
    cpu_offload_bytes_per_gpu: int,
) -> tuple[str, ...]:
    """Render exact, monotone per-GPU vLLM weight offload at MiB granularity."""
    if type(cpu_offload_bytes_per_gpu) is not int or cpu_offload_bytes_per_gpu < 0:
        raise ValueError("model CPU offload bytes must be a non-negative integer")
    if cpu_offload_bytes_per_gpu == 0:
        return ()
    offload_mib = math.ceil(cpu_offload_bytes_per_gpu / _MIB)
    # MiB/GiB is a dyadic rational, so the float parser round-trips this exact
    # capacity without under-requesting bytes.
    offload_gib = offload_mib / 1024
    return ("--cpu-offload-gb", str(offload_gib))


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

    Physical GPU count/memory/pressure is admitted by UniversalResourceAuthority
    from pure compute-capacity and runtime-pressure facts; this function only
    derives legal tensor-parallel factors from immutable model geometry.
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
    cpu_offload_bytes_per_gpu: int = 0,
) -> int:
    if total_asset_bytes <= 0:
        raise ValueError("model runtime memory planning requires positive asset bytes")
    if (
        type(cpu_offload_bytes_per_gpu) is not int
        or cpu_offload_bytes_per_gpu < 0
    ):
        raise ValueError(
            "model CPU offload bytes per GPU must be a non-negative integer"
        )
    per_device_weights = max(
        1,
        math.ceil(total_asset_bytes / tensor_parallel),
    )
    resident_weights = max(
        0,
        per_device_weights - cpu_offload_bytes_per_gpu,
    )
    kv_cache = _kv_cache_budget_bytes(
        asset_path,
        context_length=context_length,
        dtype=dtype,
        tensor_parallel=tensor_parallel,
    )
    # Cold bootstrap must cover the engine's non-KV peak before any measured
    # qualification exists. vLLM's compile/allocator/CUDA-graph workspace grows
    # with both model state and the live context/KV envelope, so a weights-only
    # margin can admit a placement that cannot initialize even one max-context
    # request. Keep the base workspace conservative, then add a bounded dynamic
    # margin proportional to the planned KV envelope. Qualified refresh replaces
    # this bootstrap estimate with measured peak GPU memory after first success.
    base_runtime_headroom = max(
        _MIN_MODEL_RUNTIME_HEADROOM_BYTES,
        math.ceil(per_device_weights * _MODEL_RUNTIME_HEADROOM_FRACTION),
    )
    kv_runtime_headroom = math.ceil(
        kv_cache * _MODEL_RUNTIME_HEADROOM_FRACTION
    )
    runtime_headroom = base_runtime_headroom + kv_runtime_headroom
    return resident_weights + kv_cache + runtime_headroom


def _model_compute_requirement(
    asset_path: Path,
    *,
    total_asset_bytes: int,
    context_length: int,
    dtype: str,
    tensor_parallel: int,
    cpu_offload_bytes_per_gpu: int = 0,
) -> ComputeRequirement:
    """Freeze hard model capacity while keeping shared-GPU load as a preference.

    VRAM residual capacity is admission-critical and durably reserved. Instantaneous
    GPU utilization is intentionally not a hard cutoff for shared serving because
    candidate discovery and allocation observe at different instants; a fixed
    utilization ceiling would turn harmless load jitter into placement TOCTOU.
    Pure placement ranks lower-utilization devices first; Authority performs admission.
    """

    required_free = _model_runtime_vram_budget_bytes(
        asset_path,
        total_asset_bytes=total_asset_bytes,
        context_length=context_length,
        dtype=dtype,
        tensor_parallel=tensor_parallel,
        cpu_offload_bytes_per_gpu=cpu_offload_bytes_per_gpu,
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
    stack: FrozenModelStack
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

    def __init__(
        self,
        message: str,
        *,
        diagnostics: Mapping[str, object] | None = None,
    ) -> None:
        if diagnostics is not None and not isinstance(diagnostics, Mapping):
            raise TypeError("model stack placement diagnostics must be a mapping or None")
        self.diagnostics = dict(diagnostics or {})
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ModelPlacementObservation:
    """One immutable authority/runtime cut used by model topology planning."""

    authority: AuthoritySnapshot
    gpu_runtime: GpuRuntimeSnapshot | None
    host_runtime: HostRuntimeSnapshot | None

    def __post_init__(self) -> None:
        if type(self.authority) is not AuthoritySnapshot:
            raise TypeError("model placement observation requires AuthoritySnapshot")
        if self.gpu_runtime is not None and type(self.gpu_runtime) is not GpuRuntimeSnapshot:
            raise TypeError("model placement GPU observation must be typed")
        if self.host_runtime is not None and type(self.host_runtime) is not HostRuntimeSnapshot:
            raise TypeError("model placement host observation must be typed")



class DockerModelStackMaterializer:
    """Freeze model bytes + immutable OCI runtime into one executable stack.

    Mutable image tags are acquisition hints only. The returned FrozenModelStack
    always carries the exact Docker image ID digest and a fingerprint collected
    from that immutable image.
    """

    def __init__(
        self,
        *,
        assets: ModelAssetManager,
        resource_authority: UniversalResourceAuthority,
        compute_inventory: ComputeInventoryPort,
        gpu_runtime_observer: GpuRuntimeObserverPort | None,
        host_runtime_observer: HostRuntimeObserverPort | None,
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
        if not isinstance(resource_authority, UniversalResourceAuthority):
            raise TypeError(
                "model stack materializer requires UniversalResourceAuthority"
            )
        if not callable(getattr(compute_inventory, "list_hosts", None)):
            raise TypeError("model stack materializer requires ComputeInventoryPort")
        if not callable(getattr(command_runner, "run", None)):
            raise TypeError("model stack materializer requires command run()")
        if not isinstance(state_root, Path):
            raise TypeError("model stack materializer state_root must be pathlib.Path")
        if not docker_executable.strip() or not vllm_default_source.strip():
            raise ValueError("Docker model runtime source identity is required")
        self._assets = assets
        self._sources = source_catalog or PackagedModelSourceCatalog()
        self._resource_authority = resource_authority
        self._compute_inventory = compute_inventory
        self._gpu_runtime_observer = gpu_runtime_observer
        self._host_runtime_observer = host_runtime_observer
        self._runner = command_runner
        self._root = state_root / "model-runtime-fingerprints"
        self._root.mkdir(parents=True, exist_ok=True)
        self._docker = docker_executable
        self._vllm_default = vllm_default_source
        self._pull_timeout = float(image_pull_timeout_seconds)
        self._fingerprint_timeout = float(fingerprint_timeout_seconds)
        self._runtime_source_lock = Lock()
        self._runtime_source_identity: tuple[
            str, str, tuple[tuple[str, str], ...]
        ] | None = None

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

    def _image_labels(self, source: str) -> dict[str, str] | None:
        result = self._runner.run(
            (
                self._docker,
                "image",
                "inspect",
                "--format",
                "{{json .Config.Labels}}",
                source,
            ),
            timeout_seconds=30.0,
        )
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        if not raw or raw == "null":
            return {}
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RuntimeError("Docker image labels are not an object")
        return {str(k): str(v) for k, v in value.items()}

    @staticmethod
    def _vllm_patch_script() -> str:
        return r"""
from pathlib import Path

root = Path("/usr/local/lib")
v1_matches = tuple(
    root.glob("python*/dist-packages/vllm/v1/worker/gpu_worker.py")
)
v0_matches = tuple(
    root.glob("python*/dist-packages/vllm/worker/worker.py")
)
if len(v1_matches) != 1 or len(v0_matches) != 1:
    raise SystemExit(
        "expected exactly one vLLM V1 and V0 GPU worker, got "
        + repr(
            (
                tuple(str(path) for path in v1_matches),
                tuple(str(path) for path in v0_matches),
            )
        )
    )

marker = "NOETRIUM_VLLM_KV_CACHE_MEMORY_BYTES"
needle = (
    "        torch.cuda.empty_cache()\n"
    "        torch.cuda.reset_peak_memory_stats()\n"
)

v1_path = v1_matches[0]
v1_source = v1_path.read_text("utf-8")
if marker in v1_source:
    raise SystemExit("vLLM V1 explicit-KV patch is already present")
if v1_source.count(needle) != 1:
    raise SystemExit("vLLM V1 memory-profiler patch anchor drifted")
v1_replacement = (
    "        explicit_kv_cache = os.environ.get("
    "\"NOETRIUM_VLLM_KV_CACHE_MEMORY_BYTES\")\n"
    "        if explicit_kv_cache is not None:\n"
    "            try:\n"
    "                explicit_kv_cache_bytes = int(explicit_kv_cache)\n"
    "            except ValueError as exc:\n"
    "                raise ValueError("
    "\"NOETRIUM_VLLM_KV_CACHE_MEMORY_BYTES must be an integer\""
    ") from exc\n"
    "            if explicit_kv_cache_bytes <= 0:\n"
    "                raise ValueError("
    "\"NOETRIUM_VLLM_KV_CACHE_MEMORY_BYTES must be positive\""
    ")\n"
    "            logger.info("
    "\"Using Authority-provided explicit KV cache memory: %.2f GiB\", "
    "explicit_kv_cache_bytes / GiB_bytes)\n"
    "            return explicit_kv_cache_bytes\n\n"
    + needle
)
v1_path.write_text(
    v1_source.replace(needle, v1_replacement, 1),
    "utf-8",
)

v0_path = v0_matches[0]
v0_source = v0_path.read_text("utf-8")
if marker in v0_source:
    raise SystemExit("vLLM V0 explicit-KV patch is already present")
if v0_source.count(needle) != 1:
    raise SystemExit("vLLM V0 memory-profiler patch anchor drifted")
v0_replacement = (
    "        explicit_kv_cache = os.environ.get("
    "\"NOETRIUM_VLLM_KV_CACHE_MEMORY_BYTES\")\n"
    "        if explicit_kv_cache is not None:\n"
    "            try:\n"
    "                explicit_kv_cache_bytes = int(explicit_kv_cache)\n"
    "            except ValueError as exc:\n"
    "                raise ValueError("
    "\"NOETRIUM_VLLM_KV_CACHE_MEMORY_BYTES must be an integer\""
    ") from exc\n"
    "            if explicit_kv_cache_bytes <= 0:\n"
    "                raise ValueError("
    "\"NOETRIUM_VLLM_KV_CACHE_MEMORY_BYTES must be positive\""
    ")\n"
    "            cache_block_size = self.get_cache_block_size_bytes()\n"
    "            if cache_block_size == 0:\n"
    "                num_gpu_blocks = 0\n"
    "                num_cpu_blocks = 0\n"
    "            else:\n"
    "                num_gpu_blocks = int("
    "explicit_kv_cache_bytes // cache_block_size)\n"
    "                num_cpu_blocks = int("
    "self.cache_config.swap_space_bytes // cache_block_size)\n"
    "            logger.info("
    "\"Using Authority-provided explicit KV cache memory: %.2f GiB "
    "(%d GPU blocks)\", "
    "explicit_kv_cache_bytes / GiB_bytes, num_gpu_blocks)\n"
    "            return max(num_gpu_blocks, 0), max(num_cpu_blocks, 0)\n\n"
    + needle
)
v0_path.write_text(
    v0_source.replace(needle, v0_replacement, 1),
    "utf-8",
)
"""

    def _materialize_patched_vllm_image(
        self,
        *,
        base_source: str,
        base_digest: str,
    ) -> tuple[str, str]:
        existing = self._image_id(_VLLM_PATCHED_SOURCE)
        if existing is not None:
            labels = self._image_labels(_VLLM_PATCHED_SOURCE) or {}
            if (
                labels.get("io.noetrium.vllm.base-image-id")
                == "sha256:" + base_digest
                and labels.get("io.noetrium.vllm.patch-revision")
                == _VLLM_PATCH_REVISION
            ):
                return _VLLM_PATCHED_SOURCE, existing

        build_root = self._root / "vllm-runtime" / _VLLM_PATCH_REVISION
        build_root.mkdir(parents=True, exist_ok=True)
        patch_path = build_root / "patch_vllm.py"
        dockerfile_path = build_root / "Dockerfile"
        atomic_replace_bytes(
            patch_path,
            self._vllm_patch_script().encode("utf-8"),
        )
        dockerfile = (
            "FROM "
            + base_source
            + "@sha256:"
            + base_digest
            + "\n"
            + "COPY patch_vllm.py /tmp/noetrium_patch_vllm.py\n"
            + "RUN python3 /tmp/noetrium_patch_vllm.py "
            + "&& rm -f /tmp/noetrium_patch_vllm.py\n"
            + 'LABEL io.noetrium.vllm.base-image-id="sha256:'
            + base_digest
            + '" '
            + 'io.noetrium.vllm.patch-revision="'
            + _VLLM_PATCH_REVISION
            + '"\n'
        )
        atomic_replace_bytes(dockerfile_path, dockerfile.encode("utf-8"))
        built = self._runner.run(
            (
                self._docker,
                "build",
                "--pull=false",
                "--tag",
                _VLLM_PATCHED_SOURCE,
                "--file",
                str(dockerfile_path),
                str(build_root),
            ),
            timeout_seconds=self._pull_timeout,
        )
        if built.returncode != 0:
            detail = (built.stderr or built.stdout).strip()
            raise RuntimeError(
                "Noetrium vLLM runtime patch build failed"
                + (": " + detail if detail else "")
            )
        digest = self._image_id(_VLLM_PATCHED_SOURCE)
        labels = self._image_labels(_VLLM_PATCHED_SOURCE) or {}
        if (
            digest is None
            or labels.get("io.noetrium.vllm.base-image-id")
            != "sha256:" + base_digest
            or labels.get("io.noetrium.vllm.patch-revision")
            != _VLLM_PATCH_REVISION
        ):
            raise RuntimeError(
                "Noetrium vLLM runtime patch image identity did not converge"
            )
        return _VLLM_PATCHED_SOURCE, digest

    def _resolve_vllm_image(self) -> tuple[str, str]:
        # Upstream release is acquisition input only. The executable runtime is
        # a Noetrium-frozen image that backports explicit KV-cache sizing so
        # UniversalResourceAuthority, not a racy global-memory profiler, owns
        # shared-GPU capacity.
        base_source = self._vllm_default
        base_digest = self._image_id(base_source)
        if base_digest is None:
            pulled = self._runner.run(
                (self._docker, "pull", base_source),
                timeout_seconds=self._pull_timeout,
            )
            if pulled.returncode != 0:
                raise RuntimeError(
                    "Docker model runtime acquisition failed: " + base_source
                )
            base_digest = self._image_id(base_source)
        if base_digest is None:
            raise RuntimeError(
                "Docker model runtime acquisition did not materialize an image"
            )
        return self._materialize_patched_vllm_image(
            base_source=base_source,
            base_digest=base_digest,
        )

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
def _sha256_path(path):
    h=hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()
engine_executable=(_sha256_path(exe) if exe.is_file() else hashlib.sha256(engine_version.encode()).hexdigest())
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
        scope: NoetriumUnit | None,
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
        scope: NoetriumUnit,
        tensor_parallel: int,
        image_digest: str,
        image_source: str,
        fingerprint: dict[str, str],
        context_length: int | None = None,
        cpu_offload_bytes_per_gpu: int = 0,
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
        effective_context = (
            config.max_position_embeddings
            if context_length is None
            else context_length
        )
        if (
            type(effective_context) is not int
            or effective_context <= 0
            or effective_context > config.max_position_embeddings
        ):
            raise ValueError(
                "runtime context length must be positive and no larger than model capability"
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
            context_length=effective_context,
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
        stack = FrozenModelStack(
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
            engine_args=(
                *_VLLM_PLATFORM_ENGINE_ARGS,
                *_cpu_offload_bytes_to_engine_args(
                    cpu_offload_bytes_per_gpu
                ),
            ),
            serving_policy=ModelServingPolicy(
                prefix_caching=True,
                chunked_prefill=True,
                runtime_tuning_revision=_VLLM_RUNTIME_TUNING_REVISION,
                kv_cache_memory_bytes=model_kv_cache_budget_bytes(
                    asset.path,
                    context_length=effective_context,
                    dtype=config.torch_dtype,
                    tensor_parallel=tensor_parallel,
                ),
            ),
        )
        intent = parse_vllm_engine_resource_args(stack.engine_args)
        base = _model_compute_requirement(
            asset.path,
            total_asset_bytes=stats.bytes,
            context_length=effective_context,
            dtype=config.torch_dtype,
            tensor_parallel=tensor_parallel,
            cpu_offload_bytes_per_gpu=intent.cpu_offload_bytes_per_gpu,
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

    def _runtime_source_cut(
        self,
    ) -> tuple[str, str, dict[str, str]]:
        """Freeze one immutable vLLM runtime source per materializer.

        Docker tags are acquisition hints only. Once resolved to the patched OCI
        image digest plus its content fingerprint, every model stack in this
        materializer must reuse that same immutable source cut. Concurrent
        callers single-flight the external Docker/fingerprint probes instead of
        re-running them for each Experiment/model role.
        """

        cached = self._runtime_source_identity
        if cached is not None:
            return cached[0], cached[1], dict(cached[2])
        with self._runtime_source_lock:
            cached = self._runtime_source_identity
            if cached is None:
                source, image_digest = self._resolve_vllm_image()
                fingerprint = self._runtime_fingerprint(
                    engine="vllm",
                    image_digest=image_digest,
                )
                cached = (
                    source,
                    image_digest,
                    tuple(sorted((str(k), str(v)) for k, v in fingerprint.items())),
                )
                self._runtime_source_identity = cached
        return cached[0], cached[1], dict(cached[2])

    def _source_context(
        self,
        model_id: str,
        *,
        scope: NoetriumUnit | None,
    ) -> tuple[NoetriumUnit, str, str, dict[str, str]]:
        asset = self._ensure_asset(model_id, scope=scope)
        holder_scope = asset.scope if scope is None else scope
        source, image_digest, fingerprint = self._runtime_source_cut()
        return holder_scope, source, image_digest, fingerprint

    def placement_observation(self) -> ModelPlacementObservation:
        return ModelPlacementObservation(
            self._resource_authority.snapshot_for_claim_kinds(
                frozenset({"compute"})
            ),
            None if self._gpu_runtime_observer is None else self._gpu_runtime_observer.snapshot(),
            None if self._host_runtime_observer is None else self._host_runtime_observer.snapshot(),
        )

    def materialize_for_tensor_parallel(
        self,
        model_id: str,
        tensor_parallel: int,
        *,
        scope: NoetriumUnit | None = None,
        context_length: int | None = None,
        cpu_offload_bytes_per_gpu: int = 0,
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
            context_length=context_length,
            cpu_offload_bytes_per_gpu=cpu_offload_bytes_per_gpu,
        )

    def materialize(
        self,
        model_id: str,
        *,
        scope: NoetriumUnit | None = None,
        minimum_context_tokens: int = 1,
        observation: ModelPlacementObservation | None = None,
    ) -> MaterializedModelStack:
        if (
            type(minimum_context_tokens) is not int
            or minimum_context_tokens <= 0
        ):
            raise ValueError("minimum model context must be positive integer")
        holder_scope, source, image_digest, fingerprint = self._source_context(
            model_id,
            scope=scope,
        )
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
        maximum_context = int(config.max_position_embeddings)
        if minimum_context_tokens > maximum_context:
            raise ModelStackPlacementUnavailable(
                "required context exceeds model capability: "
                f"{model_id}:required={minimum_context_tokens}:max={maximum_context}",
                diagnostics={
                    "model_id": model_id,
                    "minimum_context_tokens": minimum_context_tokens,
                    "maximum_context_tokens": maximum_context,
                    "reason": "context_capability",
                },
            )

        # One observation cut keeps all topology alternatives comparable and
        # avoids placement TOCTOU while searching TP/context.  Warm-reuse
        # evaluation may supply a projected cut that hypothetically releases
        # only the candidate's own resources; planning never mutates Authority.
        observed = self.placement_observation() if observation is None else observation
        if type(observed) is not ModelPlacementObservation:
            raise TypeError("model materialization observation must be typed")
        snapshot = observed.authority
        gpu_runtime = observed.gpu_runtime
        host_runtime = observed.host_runtime
        owner_generation, owner_scope_lease_id = (
            self._resource_authority.scope_ownership_cut(holder_scope)
        )
        hosts = self._compute_inventory.list_hosts()
        tensor_parallels = _tensor_parallel_candidates_for_model_geometry(
            asset.path
        )

        minimum_context_failures: dict[int, dict[str, object]] = {}

        def placement_exists(
            tensor_parallel: int,
            context_length: int,
            *,
            cpu_offload_bytes_per_gpu: int = 0,
        ) -> bool:
            requirement = _model_compute_requirement(
                asset.path,
                total_asset_bytes=stats.bytes,
                context_length=context_length,
                dtype=config.torch_dtype,
                tensor_parallel=tensor_parallel,
                cpu_offload_bytes_per_gpu=cpu_offload_bytes_per_gpu,
            )
            if cpu_offload_bytes_per_gpu:
                requirement = replace(
                    requirement,
                    memory_bytes=(
                        requirement.memory_bytes
                        + cpu_offload_bytes_per_gpu * tensor_parallel
                    ),
                )
            try:
                claims = compute_claim_candidates(
                    resource_key=(
                        "model-stack-probe:"
                        + canonical_digest(
                            {
                                "model_id": model_id,
                                "tensor_parallel": tensor_parallel,
                                "context_length": context_length,
                                "cpu_offload_bytes_per_gpu": (
                                    cpu_offload_bytes_per_gpu
                                ),
                                "compute": requirement,
                            }
                        )
                    ),
                    holder_key=scope_key(holder_scope),
                    generation=1,
                    consumer_resource_key=(
                        "model-stack-materialization:" + model_id
                    ),
                    requirement=requirement,
                    hosts=hosts,
                    authority=snapshot,
                    placement_scope=holder_scope,
                    gpu_runtime=gpu_runtime,
                    host_runtime=host_runtime,
                    owner_scope=holder_scope,
                    scope_generation=owner_generation.generation,
                    scope_lease_id=owner_scope_lease_id,
                )
            except ComputePlacementUnavailable as exc:
                if (
                    cpu_offload_bytes_per_gpu == 0
                    and context_length == minimum_context_tokens
                ):
                    minimum_context_failures[tensor_parallel] = {
                        "tensor_parallel": tensor_parallel,
                        "context_length": context_length,
                        "compute": dict(exc.diagnostics),
                    }
                return False
            return bool(claims)

        # Resource footprint is the primary placement objective.  Choose the
        # smallest legal tensor-parallel topology that satisfies the paper's
        # semantic context requirement; then preserve as much context headroom
        # as possible inside that already-minimal footprint.  This prevents a
        # larger TP topology from consuming extra GPUs merely to retain unused
        # maximum context capability.  Feasibility is monotone in context length
        # because only the KV/runtime memory envelope grows with context.
        for tensor_parallel in tensor_parallels:
            if not placement_exists(tensor_parallel, minimum_context_tokens):
                continue
            low = minimum_context_tokens
            high = maximum_context
            while low < high:
                mid = (low + high + 1) // 2
                if placement_exists(tensor_parallel, mid):
                    low = mid
                else:
                    high = mid - 1
            return self._candidate(
                model_id=model_id,
                scope=holder_scope,
                tensor_parallel=tensor_parallel,
                image_digest=image_digest,
                image_source=source,
                fingerprint=fingerprint,
                context_length=low,
            )

        # Only after every GPU-only topology is impossible do we admit vLLM's
        # canonical per-GPU CPU weight offload. Offload never substitutes for
        # KV cache or runtime workspace and remains ordinary Authority-accounted
        # host memory. For each TP topology, minimize offload at the required
        # semantic context, then maximize context without increasing that
        # offload. This preserves GPU-only performance whenever physically
        # possible and makes host spill a pressure fallback rather than a second
        # serving mode.
        for tensor_parallel in tensor_parallels:
            per_device_weights = max(
                1,
                math.ceil(stats.bytes / tensor_parallel),
            )
            max_offload_mib = math.ceil(per_device_weights / _MIB)
            max_offload_bytes = max_offload_mib * _MIB
            if not placement_exists(
                tensor_parallel,
                minimum_context_tokens,
                cpu_offload_bytes_per_gpu=max_offload_bytes,
            ):
                continue

            low_offload_mib = 1
            high_offload_mib = max_offload_mib
            while low_offload_mib < high_offload_mib:
                mid_offload_mib = (
                    low_offload_mib + high_offload_mib
                ) // 2
                if placement_exists(
                    tensor_parallel,
                    minimum_context_tokens,
                    cpu_offload_bytes_per_gpu=mid_offload_mib * _MIB,
                ):
                    high_offload_mib = mid_offload_mib
                else:
                    low_offload_mib = mid_offload_mib + 1
            cpu_offload_bytes_per_gpu = low_offload_mib * _MIB

            low_context = minimum_context_tokens
            high_context = maximum_context
            while low_context < high_context:
                mid_context = (low_context + high_context + 1) // 2
                if placement_exists(
                    tensor_parallel,
                    mid_context,
                    cpu_offload_bytes_per_gpu=cpu_offload_bytes_per_gpu,
                ):
                    low_context = mid_context
                else:
                    high_context = mid_context - 1
            return self._candidate(
                model_id=model_id,
                scope=holder_scope,
                tensor_parallel=tensor_parallel,
                image_digest=image_digest,
                image_source=source,
                fingerprint=fingerprint,
                context_length=low_context,
                cpu_offload_bytes_per_gpu=cpu_offload_bytes_per_gpu,
            )

        raise ModelStackPlacementUnavailable(
            "no compute topology can materialize model stack: " + model_id,
            diagnostics={
                "model_id": model_id,
                "minimum_context_tokens": minimum_context_tokens,
                "maximum_context_tokens": maximum_context,
                "tensor_parallel_candidates": tensor_parallels,
                "cpu_weight_offload_fallback_attempted": True,
                "minimum_context_attempts": tuple(
                    minimum_context_failures[tensor_parallel]
                    for tensor_parallel in tensor_parallels
                    if tensor_parallel in minimum_context_failures
                ),
            },
        )



__all__ = [
    "DockerModelStackMaterializer",
    "MaterializedModelStack",
    "ModelPlacementObservation",
    "ModelStackPlacementUnavailable",
    "model_kv_cache_budget_bytes",
    "model_kv_cache_bytes_per_token",
]
