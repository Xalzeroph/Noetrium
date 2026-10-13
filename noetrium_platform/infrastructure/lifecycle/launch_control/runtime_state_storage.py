from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.kernel.event_store import (
    FileCausalEventStore,
)

from .runtime_state_codec import RuntimeControlStateCodec
from .runtime_state_contracts import RuntimeControlState


class FileRuntimeControlStateStore:
    """Disposable runtime-control projection backed by causal Event Units."""

    def __init__(self, path: Path, codec: RuntimeControlStateCodec | None = None) -> None:
        self._path = path
        self._codec = codec or RuntimeControlStateCodec()
        self._journal = FileCausalEventStore(
            path,
            state_schema="runtime.control-state.v1",
        )

    def exists(self) -> bool:
        return self._journal.exists()

    def write(self, state: RuntimeControlState) -> None:
        self._journal.append(self._codec.encode(state), phase="runtime-control-state")

    def read(self) -> RuntimeControlState:
        return self._codec.decode(self._journal.read())

    def reference(self) -> str:
        return str(self._path)

    def verify_projection_rebuild(self) -> RuntimeControlState | None:
        payload = self._journal.verify_projection_rebuild()
        return None if not payload else self._codec.decode(payload)


__all__ = ["FileRuntimeControlStateStore"]
