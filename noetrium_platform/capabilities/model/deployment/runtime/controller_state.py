from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.capabilities.model._persisted import (
    exact_fields,
    integer,
    number,
    optional_integer,
    sequence,
    text,
)
from noetrium_platform.capabilities.model.deployment.api import (
    ModelControllerPhase,
    ModelControllerState,
    ModelDeploymentStatus,
    ModelDesiredState,
    ModelReconcileCycle,
    ModelRuntimeState,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes


_STATE_FIELDS = frozenset({
    "controller_id", "phase", "pid", "started_at_utc", "heartbeat_at_utc", "interval_seconds",
    "cycle_count", "detail", "last_cycle",
})
_CYCLE_FIELDS = frozenset({"cycle_index", "completed_at_utc", "statuses"})
_STATUS_FIELDS = frozenset({
    "deployment_id", "service_id", "desired_state", "runtime_state", "pid", "detail",
})


class FileModelControllerStateStore:
    """Small durable operational read model for the long-running reconcile controller."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> ModelControllerState | None:
        if not self._path.exists():
            return None
        data = exact_fields(
            json.loads(self._path.read_text("utf-8")),
            field="model controller state",
            fields=_STATE_FIELDS,
        )
        cycle_data = data["last_cycle"]
        cycle = None if cycle_data is None else self._cycle_from_data(cycle_data)
        return ModelControllerState(
            controller_id=text(data["controller_id"], field="controller_id", allow_empty=False),
            phase=ModelControllerPhase(text(data["phase"], field="phase", allow_empty=False)),
            pid=optional_integer(data["pid"], field="pid", minimum=1),
            started_at_utc=text(data["started_at_utc"], field="started_at_utc", allow_empty=False),
            heartbeat_at_utc=text(data["heartbeat_at_utc"], field="heartbeat_at_utc", allow_empty=False),
            interval_seconds=number(data["interval_seconds"], field="interval_seconds", minimum=0.0),
            cycle_count=integer(data["cycle_count"], field="cycle_count", minimum=0),
            last_cycle=cycle,
            detail=text(data["detail"], field="detail"),
        )

    def write(self, state: ModelControllerState) -> ModelControllerState:
        atomic_replace_bytes(self._path, self._encode(state))
        return state

    @staticmethod
    def _cycle_from_data(value: object) -> ModelReconcileCycle:
        data = exact_fields(value, field="model reconcile cycle", fields=_CYCLE_FIELDS)
        statuses = sequence(data["statuses"], field="statuses")
        return ModelReconcileCycle(
            cycle_index=integer(data["cycle_index"], field="cycle_index", minimum=0),
            completed_at_utc=text(data["completed_at_utc"], field="completed_at_utc", allow_empty=False),
            statuses=tuple(
                FileModelControllerStateStore._status_from_data(item)
                for item in statuses
            ),
        )

    @staticmethod
    def _status_from_data(value: object) -> ModelDeploymentStatus:
        data = exact_fields(value, field="model deployment status", fields=_STATUS_FIELDS)
        return ModelDeploymentStatus(
            deployment_id=text(data["deployment_id"], field="status.deployment_id", allow_empty=False),
            service_id=text(data["service_id"], field="status.service_id", allow_empty=False),
            desired_state=ModelDesiredState(text(data["desired_state"], field="status.desired_state", allow_empty=False)),
            runtime_state=ModelRuntimeState(text(data["runtime_state"], field="status.runtime_state", allow_empty=False)),
            pid=optional_integer(data["pid"], field="status.pid", minimum=1),
            detail=text(data["detail"], field="status.detail"),
        )

    @staticmethod
    def _encode(state: ModelControllerState) -> bytes:
        cycle = state.last_cycle
        payload = {
            "controller_id": state.controller_id,
            "phase": state.phase.value,
            "pid": state.pid,
            "started_at_utc": state.started_at_utc,
            "heartbeat_at_utc": state.heartbeat_at_utc,
            "interval_seconds": state.interval_seconds,
            "cycle_count": state.cycle_count,
            "detail": state.detail,
            "last_cycle": None if cycle is None else {
                "cycle_index": cycle.cycle_index,
                "completed_at_utc": cycle.completed_at_utc,
                "statuses": [
                    {
                        "deployment_id": status.deployment_id,
                        "service_id": status.service_id,
                        "desired_state": status.desired_state.value,
                        "runtime_state": status.runtime_state.value,
                        "pid": status.pid,
                        "detail": status.detail,
                    }
                    for status in cycle.statuses
                ],
            },
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


__all__ = ["FileModelControllerStateStore"]
