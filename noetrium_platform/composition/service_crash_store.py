from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.infrastructure.reliability.failure.api import failure_document, failure_from_dict
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceProcessIdentity
from noetrium_platform.infrastructure.lifecycle.service.runtime import ServiceExitClass

from .service_crash_contracts import CrashHandoffPhase, DurableCrashHandoff


class DurableCrashHandoffStore:
    """Durable single-record transaction journal; owns serialization only."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def _encode(handoff: DurableCrashHandoff) -> bytes:
        process = handoff.process
        payload = {
            "schema_version": handoff.schema_version,
            "handoff_id": handoff.handoff_id,
            "service_id": handoff.service_id,
            "contract_digest": handoff.contract_digest,
            "process": {
                "pid": process.pid,
                "start_identity": process.start_identity,
                "process_group_id": process.process_group_id,
                "control_pid": process.control_pid,
                "anchor_pid": process.anchor_pid,
                "anchor_start_identity": process.anchor_start_identity,
                "anchor_control_pid": process.anchor_control_pid,
            },
            "exit_class": int(handoff.exit_class),
            "stdout_capture_ref": handoff.stdout_capture_ref,
            "stderr_capture_ref": handoff.stderr_capture_ref,
            "failure": failure_document(handoff.failure),
            "phase": handoff.phase.value,
            "created_at": handoff.created_at,
            "updated_at": handoff.updated_at,
        }
        return json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def write(self, handoff: DurableCrashHandoff) -> None:
        atomic_replace_bytes(self.path, self._encode(handoff))

    def read(self) -> DurableCrashHandoff:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if int(raw["schema_version"]) != self.SCHEMA_VERSION:
            raise ValueError("unsupported durable crash handoff schema")
        raw["process"] = ServiceProcessIdentity(**raw["process"])
        raw["exit_class"] = ServiceExitClass(int(raw["exit_class"]))
        raw["failure"] = failure_from_dict(raw["failure"])
        raw["phase"] = CrashHandoffPhase(raw["phase"])
        return DurableCrashHandoff(**raw)


__all__ = ["DurableCrashHandoffStore"]
