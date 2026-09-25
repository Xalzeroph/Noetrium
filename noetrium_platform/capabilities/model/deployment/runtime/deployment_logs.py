from __future__ import annotations

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentCatalogPort,
    ModelDeploymentLogs,
    ModelLogTail,
    ModelServiceRuntimeFactoryPort,
)

from .launch_materializer import ModelLaunchMaterializer
from .applied_store import AppliedModelDeploymentStore


class ModelDeploymentLogReader:
    """Read-only deployment log locator/tailer."""

    def __init__(
        self,
        applied_store: AppliedModelDeploymentStore,
        catalog: ModelDeploymentCatalogPort,
        materializer: ModelLaunchMaterializer,
        service_factory: ModelServiceRuntimeFactoryPort,
    ) -> None:
        self._applied_store = applied_store
        self._catalog = catalog
        self._materializer = materializer
        self._service_factory = service_factory

    def logs(self, deployment_id: str) -> ModelDeploymentLogs:
        applied = self._applied_store.read(deployment_id)
        if applied is not None:
            return self._service_factory.logs(applied.contract, deployment_id=deployment_id)
        contract, _ = self._materializer.materialize(self._catalog.deployment(deployment_id))
        return self._service_factory.logs(contract, deployment_id=deployment_id)

    def tail_logs(self, deployment_id: str, *, stream: str = "stderr", max_bytes: int = 8192) -> ModelLogTail:
        if stream not in {"stdout", "stderr"}:
            raise ValueError("stream must be stdout or stderr")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        logs = self.logs(deployment_id)
        path = logs.stdout_path if stream == "stdout" else logs.stderr_path
        if not path.exists():
            return ModelLogTail(deployment_id, stream, path, 0, "")
        size = path.stat().st_size
        # Read a bounded expansion window because CRLF can consume two source
        # bytes for one logical newline in the returned tail.
        count = min(size, max_bytes * 2)
        with path.open("rb") as handle:
            handle.seek(size - count)
            raw = handle.read(count)
        # Log tails are a logical text view. Windows text writers may persist
        # CRLF while the platform contract exposes newline-stable evidence;
        # normalize before applying the caller's visible-byte bound so a tail
        # is not shortened by an invisible carriage return.
        normalized = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        if len(normalized) > max_bytes:
            normalized = normalized[-max_bytes:]
        return ModelLogTail(
            deployment_id,
            stream,
            path,
            len(raw),
            normalized.decode("utf-8", errors="replace"),
        )


__all__ = ["ModelDeploymentLogReader"]
