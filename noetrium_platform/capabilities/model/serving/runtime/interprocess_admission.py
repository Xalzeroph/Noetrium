from __future__ import annotations

from pathlib import Path
from threading import Lock
import time

from noetrium_platform.foundation.kernel.concurrency.api import CancellationTokenPort, TaskCancelled
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import InterprocessFileLock, InterprocessLockBusy
from ..api.admission import ModelAdmissionClosed, ModelAdmissionTimeout
from .admission import AdmissionSnapshot, ModelAdmissionController


class _Lease:
    def __init__(self, local, slot: InterprocessFileLock) -> None:
        self._local, self._slot, self._released, self._lock = local, slot, False, Lock()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            errors = []
            try:
                self._slot.__exit__(None, None, None)
            except BaseException as exc:
                errors.append(exc)
            try:
                self._local.release()
            except BaseException as exc:
                errors.append(exc)
            self._released = True
            if errors:
                raise ExceptionGroup("interprocess model admission release failed", errors)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb
        self.release()


class InterprocessModelAdmissionController:
    """Owner-fair local admission plus one crash-safe host-wide slot fence."""

    _POLL_SECONDS = 0.01

    def __init__(self, root: Path, *, deployment_id: str, deployment_generation: str, qualified_capacity: int) -> None:
        if not isinstance(root, Path):
            raise TypeError("interprocess model admission root must be Path")
        if not deployment_id.strip():
            raise ValueError("model admission deployment_id is required")
        if len(deployment_generation) != 64 or any(c not in "0123456789abcdef" for c in deployment_generation):
            raise ValueError("model admission deployment_generation must be SHA-256")
        if type(qualified_capacity) is not int or qualified_capacity <= 0:
            raise ValueError("qualified capacity must be positive")
        identity = canonical_digest({"deployment_id": deployment_id, "deployment_generation": deployment_generation})
        self.capacity = qualified_capacity
        self._directory = root.expanduser().absolute() / identity
        if self._directory.exists() and (self._directory.is_symlink() or not self._directory.is_dir()):
            raise RuntimeError("model admission authority path has invalid identity")
        self._directory.mkdir(parents=True, exist_ok=True)
        self._verify_capacity()
        self._local = ModelAdmissionController(qualified_capacity)
        self._closed = False
        self._state_lock = Lock()

    def _verify_capacity(self) -> None:
        marker = self._directory / "qualified-capacity.txt"
        with InterprocessFileLock(self._directory / "qualified-capacity.lock"):
            if marker.exists():
                if marker.is_symlink() or not marker.is_file():
                    raise RuntimeError("model admission capacity marker is invalid")
                try:
                    observed = int(marker.read_text("utf-8").strip())
                except (OSError, ValueError) as exc:
                    raise RuntimeError("model admission capacity marker is corrupt") from exc
                if observed != self.capacity:
                    raise ValueError("qualified admission capacity drift for deployment generation")
            else:
                atomic_replace_bytes(marker, f"{self.capacity}\n".encode("ascii"))

    @staticmethod
    def _cancelled(cancellation) -> bool:
        return cancellation is not None and cancellation.cancelled

    @staticmethod
    def _reason(cancellation) -> str:
        return cancellation.reason if cancellation is not None and cancellation.reason else "model admission cancelled"

    def _slot_order(self, owner_id: str | None) -> tuple[int, ...]:
        start = int(canonical_digest(owner_id or "__anonymous__")[:16], 16) % self.capacity
        return tuple((start + i) % self.capacity for i in range(self.capacity))

    def _acquire_slot(self, deadline: float | None, cancellation, owner_id: str | None) -> InterprocessFileLock:
        while True:
            with self._state_lock:
                if self._closed:
                    raise ModelAdmissionClosed("interprocess model admission controller is closed")
            if self._cancelled(cancellation):
                raise TaskCancelled(self._reason(cancellation))
            for slot in self._slot_order(owner_id):
                lock = InterprocessFileLock(self._directory / f"slot-{slot:08d}.lock", blocking=False)
                try:
                    lock.__enter__()
                except InterprocessLockBusy:
                    continue
                return lock
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise ModelAdmissionTimeout("model admission timed out at host-wide qualified capacity")
            time.sleep(self._POLL_SECONDS if remaining is None else min(self._POLL_SECONDS, remaining))

    def acquire(self, timeout_seconds: float | None = None, *, cancellation: CancellationTokenPort | None = None, owner_id: str | None = None) -> _Lease:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("model admission timeout cannot be negative")
        deadline = None if timeout_seconds is None else time.monotonic() + float(timeout_seconds)
        local = self._local.acquire(timeout_seconds, cancellation=cancellation, owner_id=owner_id)
        try:
            slot = self._acquire_slot(deadline, cancellation, owner_id)
        except BaseException:
            local.release()
            raise
        return _Lease(local, slot)

    def snapshot(self) -> AdmissionSnapshot:
        return self._local.snapshot()

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        self._local.close()

    @property
    def closed(self) -> bool:
        with self._state_lock:
            return self._closed


class InterprocessModelAdmissionRegistry:
    """Host-visible model admission registry for exact deployment generations."""

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            raise TypeError("interprocess model admission registry root must be Path")
        self._root = root.expanduser().absolute()
        if self._root.exists() and (self._root.is_symlink() or not self._root.is_dir()):
            raise RuntimeError("model admission registry root has invalid identity")
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock, self._controllers, self._closed = Lock(), {}, False

    def controller_for(self, *, deployment_id: str, deployment_generation: str, qualified_capacity: int) -> InterprocessModelAdmissionController:
        key = (deployment_id, deployment_generation)
        with self._lock:
            if self._closed:
                raise ModelAdmissionClosed("model admission registry is closed")
            controller = self._controllers.get(key)
            if controller is None:
                controller = InterprocessModelAdmissionController(self._root, deployment_id=deployment_id, deployment_generation=deployment_generation, qualified_capacity=qualified_capacity)
                self._controllers[key] = controller
            elif controller.capacity != qualified_capacity:
                raise ValueError("qualified admission capacity drift for deployment generation")
            return controller

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            controllers = tuple(self._controllers.values())
        for controller in controllers:
            controller.close()

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed


__all__ = ["InterprocessModelAdmissionController", "InterprocessModelAdmissionRegistry"]
