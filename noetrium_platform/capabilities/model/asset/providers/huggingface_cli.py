from __future__ import annotations

from collections.abc import Mapping
import os
import shutil
from pathlib import Path

from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandRunnerPort, LocalCommandStartError, LocalCommandTimeoutError
from noetrium_platform.capabilities.model.asset.api import (
    ModelAcquisitionReceipt,
    ModelAssetStoragePort,
    ModelSourceSpec,
)


class HuggingFaceCliModelSource:
    """Explicit operator-triggered Hugging Face download backend."""

    backend_id = "huggingface"

    def __init__(
        self,
        storage: ModelAssetStoragePort,
        *,
        executable: str = "hf",
        cache_root: Path | None = None,
        environment: Mapping[str, str] | None = None,
        command_runner: LocalCommandRunnerPort,
        command_timeout_seconds: float = 86400.0,
    ) -> None:
        self._storage = storage
        self._executable = executable
        self._cache_root = cache_root
        self._command_runner = command_runner
        self._command_timeout_seconds = float(command_timeout_seconds)
        if self._command_timeout_seconds <= 0:
            raise ValueError("model source command timeout must be positive")
        self._environment = tuple(
            sorted((str(key), str(value)) for key, value in (environment or {}).items())
        )
        if self._cache_root is not None:
            self._cache_root.mkdir(parents=True, exist_ok=True)

    def acquire(self, model_id: str, spec: ModelSourceSpec) -> ModelAcquisitionReceipt:
        destination = self._storage.target(model_id, pool_id=spec.storage_pool)
        if destination.is_symlink():
            raise FileExistsError(f"model target is a symlink: {model_id}")
        if destination.exists() and not spec.resume:
            raise FileExistsError(f"model target already exists: {model_id}")
        executable = shutil.which(self._executable)
        if executable is None:
            raise FileNotFoundError(self._executable)
        argv = [executable, "download", spec.source, "--local-dir", str(destination)]
        if spec.revision:
            argv.extend(("--revision", spec.revision))
        for pattern in spec.include:
            argv.extend(("--include", pattern))
        for pattern in spec.exclude:
            argv.extend(("--exclude", pattern))
        if spec.max_workers is not None:
            argv.extend(("--max-workers", str(spec.max_workers)))
        process_environment = None
        if self._environment or self._cache_root is not None:
            # Recent Hugging Face CLI versions reject --cache-dir together with
            # --local-dir. HF_HOME keeps the cache explicit without changing
            # the managed asset destination or sacrificing resumability.
            process_environment = os.environ.copy()
            process_environment.update(dict(self._environment))
            if self._cache_root is not None:
                process_environment["HF_HOME"] = str(self._cache_root)
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
            raise RuntimeError("model source acquisition failed")
        return ModelAcquisitionReceipt(model_id, self.backend_id, spec.source, destination, spec.revision, spec.storage_pool)


__all__ = ["HuggingFaceCliModelSource"]
