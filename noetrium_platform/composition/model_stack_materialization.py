from __future__ import annotations

from dataclasses import dataclass
import json
import re
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
_RUNTIME_FINGERPRINT_SCHEMA = "noetrium.docker-model-runtime-fingerprint.v1"
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+){1,3})(?:[-+].*)?$")


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
        vllm_default_source: str = _VLLM_REPOSITORY + ":latest",
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

    @staticmethod
    def _version_key(reference: str) -> tuple[int, ...] | None:
        tag = reference.rpartition(":")[2]
        match = _VERSION_RE.fullmatch(tag)
        if match is None:
            return None
        return tuple(int(part) for part in match.group(1).split("."))

    def _local_vllm_source(self) -> str | None:
        result = self._runner.run(
            (
                self._docker,
                "image",
                "ls",
                "--format",
                "{{.Repository}}:{{.Tag}}",
                _VLLM_REPOSITORY,
            ),
            timeout_seconds=30.0,
        )
        if result.returncode != 0:
            raise RuntimeError("Docker image inventory failed")
        candidates = tuple(
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip()
            and not line.strip().endswith(":<none>")
        )
        versioned = tuple(
            (key, ref)
            for ref in candidates
            if (key := self._version_key(ref)) is not None
        )
        if versioned:
            return max(versioned, key=lambda row: row[0])[1]
        if self._vllm_default in candidates:
            return self._vllm_default
        return None

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
        source = self._local_vllm_source() or self._vllm_default
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
        if asset is not None:
            usage = self._assets.model_usage(model_id)
            if usage.deployment_ids or usage.desired_running_deployment_ids:
                raise RuntimeError(
                    "inaccessible model asset retains deployment references: "
                    + model_id
                )
            self._assets.unregister_model(
                model_id,
                delete_managed_files=False,
            )
        entry = self._sources.resolve(model_id)
        return self._assets.fetch_model(
            model_id,
            PLATFORM_SCOPE if scope is None else scope,
            entry.source,
            family=entry.family,
            tags=entry.tags,
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
                "--gpu-memory-utilization",
                "0.85",
            ),
            serving_policy=ModelServingPolicy(),
        )
        per_device_weights = max(
            1,
            (stats.bytes + tensor_parallel - 1) // tensor_parallel,
        )
        required_free = per_device_weights + 2 * _GIB
        base = ComputeRequirement(
            cpu_cores=4,
            memory_bytes=max(4 * _GIB, min(stats.bytes, 16 * _GIB)),
            gpu_count=tensor_parallel,
            required_gpu_free_memory_bytes=required_free,
            max_gpu_utilization_percent=50,
            gpu_sharing_mode=GpuSharingMode.IDLE_ONLY,
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

    def materialize(
        self,
        model_id: str,
        *,
        scope: ScopeIdentity | None = None,
        max_tensor_parallel: int = 8,
    ) -> MaterializedModelStack:
        asset = self._ensure_asset(model_id, scope=scope)
        holder_scope = asset.scope if scope is None else scope
        source, image_digest = self._resolve_vllm_image()
        fingerprint = self._runtime_fingerprint(
            engine="vllm",
            image_digest=image_digest,
        )
        for tensor_parallel in range(1, max_tensor_parallel + 1):
            candidate = self._candidate(
                model_id=model_id,
                scope=holder_scope,
                tensor_parallel=tensor_parallel,
                image_digest=image_digest,
                image_source=source,
                fingerprint=fingerprint,
            )
            if self._compute.candidates(
                candidate.compute,
                scope=holder_scope,
            ):
                return candidate
        raise RuntimeError(
            "no compute topology can materialize model stack: " + model_id
        )


__all__ = [
    "DockerModelStackMaterializer",
    "MaterializedModelStack",
]
