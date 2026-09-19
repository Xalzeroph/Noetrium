from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from noetrium_platform.infrastructure.reliability.failure.api import failure_from_dict
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
        payload = asdict(handoff)
        payload["process"] = asdict(handoff.process)
        payload["exit_class"] = int(handoff.exit_class)
        payload["failure"] = handoff.failure.to_dict()
        payload["phase"] = handoff.phase.value
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
