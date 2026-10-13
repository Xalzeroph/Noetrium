from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import os

from noetrium_platform.capabilities.model.deployment.api import (
    ModelControllerPhase,
    ModelControllerState,
    ModelControllerStatePort,
    ModelControllerStopPort,
    ModelFleetRuntimePort,
    ModelReconcileCycle,
)


class ModelDesiredStateController:
    """Continuously converges mutable management desired state to service runtime state.

    This is deliberately a foreground, backend-neutral controller.  tmux,
    systemd, containers or a remote scheduler may keep this process alive;
    none of those persistence mechanisms leak into model management.
    """

    def __init__(
        self,
        deployments: ModelFleetRuntimePort,
        state: ModelControllerStatePort,
        *,
        controller_id: str = "model-desired-state",
    ) -> None:
        if not controller_id:
            raise ValueError("controller_id required")
        self._deployments = deployments
        self._state = state
        self._controller_id = controller_id

    def snapshot(self) -> ModelControllerState | None:
        return self._state.read()

    def run(
        self,
        *,
        interval_seconds: float,
        stop: ModelControllerStopPort,
        max_cycles: int | None = None,
    ) -> ModelControllerState:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if max_cycles is not None and max_cycles <= 0:
            raise ValueError("max_cycles must be positive")

        started_at = self._now()
        current = ModelControllerState(
            controller_id=self._controller_id,
            phase=ModelControllerPhase.RUNNING,
            pid=os.getpid(),
            started_at_utc=started_at,
            heartbeat_at_utc=started_at,
            interval_seconds=interval_seconds,
            cycle_count=0,
        )
        self._state.write(current)
        try:
            while True:
                statuses = self._deployments.reconcile()
                cycle_index = current.cycle_count + 1
                heartbeat = self._now()
                cycle = ModelReconcileCycle(cycle_index, heartbeat, statuses)
                current = replace(
                    current,
                    heartbeat_at_utc=heartbeat,
                    cycle_count=cycle_index,
                    last_cycle=cycle,
                    detail="",
                )
                self._state.write(current)
                if max_cycles is not None and cycle_index >= max_cycles:
                    break
                if stop.wait(interval_seconds):
                    break
        except Exception as exc:
            current = replace(
                current,
                phase=ModelControllerPhase.ERROR,
                heartbeat_at_utc=self._now(),
                detail=type(exc).__name__,
            )
            self._state.write(current)
            raise
        except BaseException as exc:
            interrupted = replace(
                current,
                phase=ModelControllerPhase.STOPPED,
                pid=None,
                heartbeat_at_utc=self._now(),
                detail=f"interrupted:{type(exc).__name__}",
            )
            self._state.write(interrupted)
            raise
        final = replace(
            current,
            phase=ModelControllerPhase.STOPPED,
            pid=None,
            heartbeat_at_utc=self._now(),
        )
        return self._state.write(final)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


__all__ = ["ModelDesiredStateController"]
