from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PromptBlockKind(StrEnum):
    VERIFIED_STATE = "verified_state"
    TASK = "task"
    MEMORY_CONTEXT = "memory_context"
    TOOL_CATALOG = "tool_catalog"
    PRIOR_OUTCOME = "prior_outcome"
    ARCHITECTURE_OBSERVATION = "architecture_observation"
    FAILURE_EVIDENCE = "failure_evidence"


@dataclass(frozen=True, slots=True)
class PromptBlock:
    kind: PromptBlockKind
    content: str
    source_digest: str
    sequence: int


@dataclass(frozen=True, slots=True)
class PromptBlockPolicy:
    role: str
    required: frozenset[PromptBlockKind]
    allowed: frozenset[PromptBlockKind]
    max_chars_by_kind: tuple[tuple[PromptBlockKind, int], ...]

    def max_chars(self, kind: PromptBlockKind) -> int:
        return dict(self.max_chars_by_kind)[kind]
