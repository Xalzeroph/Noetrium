from __future__ import annotations

from collections.abc import Mapping
import json
import os
import re
import shutil
from pathlib import Path

from noetrium_platform.substrate.api import LocalCommandRunnerPort, LocalCommandStartError, LocalCommandTimeoutError
from noetrium_platform.capabilities.model.asset.api import (
    ModelAcquisitionReceipt,
    ModelAssetMode,
    ModelAssetStoragePort,
    ModelAcquisitionRequest,
)


def _diagnostic_tail(value: str, *, limit: int = 4096) -> str:
    text = str(value).replace("\x00", "\uFFFD").strip()
    if len(text) <= limit:
        return text
    return "...[truncated]" + text[-limit:]


_HF_REPO_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_HF_PINNED_REVISION = re.compile(r"[0-9a-f]{40}")
_HF_WEIGHT_INDEXES = (
    "model.safetensors.index.json",
    "pytorch_model.bin.index.json",
)
_HF_TOKENIZER_FILES = ("tokenizer.json", "tokenizer.model", "spiece.model")


def _safe_snapshot_file(root: Path, relative: str) -> Path | None:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        return None
    resolved = root.joinpath(candidate)
    return resolved if resolved.is_file() else None


def _complete_pinned_snapshot(
    cache_root: Path,
    spec: ModelAcquisitionRequest,
) -> Path | None:
    """Return an exact cached serving closure without claiming full repo closure."""

    if spec.include or spec.exclude or spec.revision is None:
        return None
    if _HF_PINNED_REVISION.fullmatch(spec.revision) is None:
        return None
    parts = spec.source.split("/")
    if len(parts) != 2 or any(
        _HF_REPO_SEGMENT.fullmatch(part) is None for part in parts
    ):
        return None
    snapshot = (
        cache_root
        / "hub"
        / ("models--" + "--".join(parts))
        / "snapshots"
        / spec.revision
    )
    if not snapshot.is_dir() or snapshot.is_symlink():
        return None
    config = snapshot / "config.json"
    if not config.is_file():
        return None
    try:
        config_value = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(config_value, dict):
        return None
    if not any((snapshot / name).is_file() for name in _HF_TOKENIZER_FILES):
        return None

    for name in _HF_WEIGHT_INDEXES:
        index = snapshot / name
        if not index.is_file():
            continue
        try:
            document = json.loads(index.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        weight_map = document.get("weight_map") if isinstance(document, dict) else None
        if not isinstance(weight_map, dict) or not weight_map:
            return None
        referenced = set(weight_map.values())
        if any(type(value) is not str for value in referenced):
            return None
        if any(_safe_snapshot_file(snapshot, value) is None for value in referenced):
            return None
        return snapshot

    if any(
        path.is_file() and path.suffix.lower() in {".safetensors", ".bin"}
        for path in snapshot.iterdir()
    ):
        return snapshot
    return None


class HuggingFaceCliModelSource:
    """Explicit operator-triggered Hugging Face download backend."""

    backend_id = "huggingface"

    def __init__(
        self,
        storage: ModelAssetStoragePort,
        *,
        executable: str = "hf",
        cache_root: Path | None = None,
        external_cache_root: Path | None = None,
        environment: Mapping[str, str] | None = None,
        command_runner: LocalCommandRunnerPort,
        command_timeout_seconds: float = 86400.0,
    ) -> None:
        self._storage = storage
        self._executable = executable
        self._cache_root = cache_root
        self._external_cache_root = (
            None
            if external_cache_root is None
            else external_cache_root.expanduser().resolve()
        )
        if (
            self._external_cache_root is not None
            and not self._external_cache_root.is_dir()
        ):
            raise ValueError(
                "external Hugging Face cache root must be an existing directory"
            )
        self._command_runner = command_runner
        self._command_timeout_seconds = float(command_timeout_seconds)
        if self._command_timeout_seconds <= 0:
            raise ValueError("model source command timeout must be positive")
        self._environment = tuple(
            sorted((str(key), str(value)) for key, value in (environment or {}).items())
        )
        if self._cache_root is not None:
            self._cache_root.mkdir(parents=True, exist_ok=True)

    def acquire(self, model_id: str, spec: ModelAcquisitionRequest) -> ModelAcquisitionReceipt:
        destination = self._storage.target(
            model_id,
            pool_id=spec.storage_pool,
        )
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"model target already exists: {model_id}")
        cache_root = self._cache_root
        destination.parent.mkdir(parents=True, exist_ok=True)
        if (
            cache_root is None
            or cache_root.stat().st_dev != destination.parent.stat().st_dev
        ):
            cache_root = destination.parent / ".noetrium-huggingface-cache"
        cache_root.mkdir(parents=True, exist_ok=True)

        snapshot_roots: list[Path] = []
        for candidate_root in (self._external_cache_root, cache_root):
            if candidate_root is None:
                continue
            resolved_root = candidate_root.expanduser().resolve()
            if resolved_root not in snapshot_roots:
                snapshot_roots.append(resolved_root)
        for snapshot_root in snapshot_roots:
            cached = _complete_pinned_snapshot(snapshot_root, spec)
            if cached is None:
                continue
            path = self._storage.materialize(
                model_id,
                cached,
                ModelAssetMode.FETCHED,
                pool_id=spec.storage_pool,
            )
            return ModelAcquisitionReceipt(
                model_id,
                self.backend_id,
                spec.source,
                path,
                spec.revision,
                spec.storage_pool,
            )

        executable = shutil.which(self._executable)
        if executable is None:
            raise FileNotFoundError(self._executable)
        argv = [executable, "download", spec.source]
        if spec.revision:
            argv.extend(("--revision", spec.revision))
        for pattern in spec.include:
            argv.extend(("--include", pattern))
        for pattern in spec.exclude:
            argv.extend(("--exclude", pattern))
        if spec.max_workers is not None:
            argv.extend(("--max-workers", str(spec.max_workers)))
        process_environment = os.environ.copy()
        process_environment.update(dict(self._environment))
        process_environment["HF_HOME"] = str(cache_root)
        try:
            completed = self._command_runner.run(
                tuple(argv),
                timeout_seconds=self._command_timeout_seconds,
                environment=process_environment,
            )
        except LocalCommandTimeoutError as exc:
            raise TimeoutError("model source acquisition timed out") from exc
        except LocalCommandStartError as exc:
            raise RuntimeError("model source acquisition failed to spawn") from exc
        if completed.returncode != 0:
            diagnostics = [f"exit={completed.returncode}"]
            stderr = _diagnostic_tail(completed.stderr)
            stdout = _diagnostic_tail(completed.stdout)
            if stderr:
                diagnostics.append(f"stderr_tail={stderr!r}")
            if stdout:
                diagnostics.append(f"stdout_tail={stdout!r}")
            raise RuntimeError(
                "model source acquisition failed: " + "; ".join(diagnostics)
            )

        cached: Path | None = None
        for line in reversed(completed.stdout.splitlines()):
            candidate = Path(line.strip()).expanduser()
            if line.strip() and candidate.exists():
                cached = candidate.resolve()
                break
        if cached is None:
            raise RuntimeError(
                "model source acquisition did not publish a cache path"
            )
        path = self._storage.materialize(
            model_id,
            cached,
            ModelAssetMode.FETCHED,
            pool_id=spec.storage_pool,
        )
        return ModelAcquisitionReceipt(
            model_id,
            self.backend_id,
            spec.source,
            path,
            spec.revision,
            spec.storage_pool,
        )


__all__ = ["HuggingFaceCliModelSource"]
