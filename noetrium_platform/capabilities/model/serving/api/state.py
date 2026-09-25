from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import time
from noetrium_platform.foundation.kernel.kernel.identity import ImmutableModelIdentity


class ModelPhase(StrEnum):
    NEW = "new"
    INVENTORY = "inventory"
    PREPARE = "prepare"
    LOAD = "load"
    WARMUP = "warmup"
    READY = "ready"
    RUNNING = "running"
    DRAINING = "draining"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True, slots=True)
class ModelRunState:
    run_id: str
    identity: ImmutableModelIdentity
    deployment_digest: str
    phase: ModelPhase
    created_at: float
    updated_at: float
    pid: int | None = None
    endpoint: str | None = None
    last_failure_id: str | None = None
    checkpoint_ref: str | None = None

    def __post_init__(self) -> None:
        for field in ("created_at", "updated_at"):
            value = getattr(self, field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value < 0
            ):
                raise ValueError(f"model run {field} must be finite and non-negative")

    @classmethod
    def initial(cls, run_id: str, identity: ImmutableModelIdentity, deployment_digest: str) -> "ModelRunState":
        if not deployment_digest:
            raise ValueError("model run requires frozen deployment digest")
        now = time.time()
        return cls(run_id, identity, deployment_digest, ModelPhase.NEW, now, now)

    def transition(self, phase: ModelPhase, **changes: object) -> "ModelRunState":
        allowed = {
            ModelPhase.NEW: {ModelPhase.INVENTORY, ModelPhase.FAILED},
            ModelPhase.INVENTORY: {ModelPhase.PREPARE, ModelPhase.FAILED},
            ModelPhase.PREPARE: {ModelPhase.LOAD, ModelPhase.FAILED, ModelPhase.INTERRUPTED},
            ModelPhase.LOAD: {ModelPhase.WARMUP, ModelPhase.FAILED, ModelPhase.INTERRUPTED},
            ModelPhase.WARMUP: {ModelPhase.READY, ModelPhase.FAILED, ModelPhase.INTERRUPTED},
            ModelPhase.READY: {ModelPhase.RUNNING, ModelPhase.STOPPING, ModelPhase.FAILED},
            ModelPhase.RUNNING: {ModelPhase.DRAINING, ModelPhase.STOPPING, ModelPhase.FAILED, ModelPhase.INTERRUPTED},
            ModelPhase.DRAINING: {ModelPhase.STOPPING, ModelPhase.FAILED, ModelPhase.INTERRUPTED},
            ModelPhase.STOPPING: {ModelPhase.STOPPED, ModelPhase.FAILED},
            ModelPhase.INTERRUPTED: {ModelPhase.RECOVERY_REQUIRED, ModelPhase.STOPPED},
            ModelPhase.FAILED: {ModelPhase.RECOVERY_REQUIRED, ModelPhase.STOPPED},
            ModelPhase.RECOVERY_REQUIRED: {ModelPhase.INVENTORY, ModelPhase.STOPPED},
            ModelPhase.STOPPED: set(),
        }
        if phase not in allowed[self.phase]:
            raise ValueError(f"illegal model phase transition {self.phase}->{phase}")
        values = {
            "run_id": self.run_id, "identity": self.identity, "deployment_digest": self.deployment_digest, "phase": phase,
            "created_at": self.created_at, "updated_at": time.time(), "pid": self.pid,
            "endpoint": self.endpoint, "last_failure_id": self.last_failure_id,
            "checkpoint_ref": self.checkpoint_ref,
        }
        values.update(changes)
        return ModelRunState(**values)
