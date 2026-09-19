from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RecoveryStateView:
    exists: bool
    attempt_id: str | None
    source_run_id: str | None
    phase: str | None
    completed_steps: tuple[str, ...]
    current_step: str | None
    current_step_status: str | None
    current_effect_certainty: str | None
    evidence_refs: tuple[str, ...]
    updated_at: float | None


def read_recovery_state(path: Path) -> RecoveryStateView:
    if not path.exists():
        return RecoveryStateView(False, None, None, None, (), None, None, None, (), None)
    data = json.loads(path.read_text(encoding="utf-8"))
    return RecoveryStateView(
        True, data.get("attempt_id"), data.get("source_run_id"), data.get("phase"),
        tuple(data.get("completed_steps", ())), data.get("current_step"), data.get("current_step_status"),
        data.get("current_effect_certainty"), tuple(data.get("evidence_refs", ())), data.get("updated_at"),
    )
