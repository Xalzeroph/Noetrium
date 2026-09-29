from __future__ import annotations

from dataclasses import dataclass, field, fields
import time

from noetrium_platform.foundation.kernel.kernel.context import (
    ExecutionContext,
    execution_context_payload,
)
from noetrium_platform.foundation.kernel.kernel.canonical import thaw_json


@dataclass(frozen=True, slots=True)
class MutationRecord:
    mutation_id: str
    state_name: str
    aggregate_id: str
    expected_version: int | None
    new_version: int
    old_digest: str | None
    new_digest: str
    component_id: str
    operation_id: str
    context: ExecutionContext
    phase: str = "committed"
    created_at: float = field(default_factory=time.time)
    effect_ref: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload = {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.name != "context"
        }
        payload["context"] = thaw_json(execution_context_payload(self.context))
        return payload
