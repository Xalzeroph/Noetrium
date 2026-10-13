from __future__ import annotations

from threading import RLock


class InMemoryProjectionCheckpointStore:
    def __init__(self) -> None:
        self._values = {}
        self._lock = RLock()

    def load(self, projector_id: str):
        with self._lock:
            return self._values.get(projector_id)

    def save(self, checkpoint) -> None:
        with self._lock:
            current = self._values.get(checkpoint.projector_id)
            if current is not None:
                if checkpoint.cursor.position < current.cursor.position:
                    raise RuntimeError("projection checkpoint regression")
                if checkpoint.cursor.position == current.cursor.position:
                    if checkpoint != current:
                        raise RuntimeError("projection checkpoint identity changed at the same watermark")
                    return
            self._values[checkpoint.projector_id] = checkpoint


__all__ = ["InMemoryProjectionCheckpointStore"]
