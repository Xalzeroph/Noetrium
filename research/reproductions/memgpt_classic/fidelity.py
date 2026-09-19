from __future__ import annotations

from dataclasses import dataclass


MEMGPT_PAPER_ERA_ANCHOR = "15540c24ac328c995fb11f89d2e228cde508ab37"
MEMGPT_CONTEXT_OVERFLOW_FIX = "12ca6e98affc9d774b7ddc0e087217122ba2a74b"


@dataclass(frozen=True, slots=True)
class MemGPTClassicFidelity:
    """Auditable paper-era MemGPT paging semantics.

    ``MEMGPT_PAPER_ERA_ANCHOR`` is an October 2023 official repository commit
    explicitly fixing paging. The later October overflow-fix commit is retained
    as corroborating evidence, not silently substituted for the anchor.
    """

    source_repository: str = "https://github.com/letta-ai/letta"
    audited_anchor_commit: str = MEMGPT_PAPER_ERA_ANCHOR
    context_overflow_fix_commit: str = MEMGPT_CONTEXT_OVERFLOW_FIX
    agent_source_artifact: str = "memgpt/agent.py"
    core_memory_in_context: bool = True
    core_memory_edit_rebuilds_prompt: bool = True
    recall_memory_external: bool = True
    archival_memory_external: bool = True
    recall_default_page_size: int = 5
    archival_default_page_size: int = 5
    overflow_strategy: str = "summarize_then_retry_same_step"
    preserve_system_message_during_summary: bool = True
    default_summary_fraction: float = 0.5

    def __post_init__(self) -> None:
        if len(self.audited_anchor_commit) != 40 or len(self.context_overflow_fix_commit) != 40:
            raise ValueError("MemGPT fidelity commits must be git SHAs")
        if not self.core_memory_in_context or not self.core_memory_edit_rebuilds_prompt:
            raise ValueError("classic MemGPT requires editable in-context core memory")
        if not self.recall_memory_external or not self.archival_memory_external:
            raise ValueError("classic MemGPT requires external recall and archival memory")
        if (self.recall_default_page_size, self.archival_default_page_size) != (5, 5):
            raise ValueError("classic MemGPT memory paging defaults drifted")
        if self.overflow_strategy != "summarize_then_retry_same_step":
            raise ValueError("classic MemGPT overflow strategy drifted")
        if not self.preserve_system_message_during_summary or self.default_summary_fraction != 0.5:
            raise ValueError("classic MemGPT summarization semantics drifted")


MEMGPT_CLASSIC_FIDELITY = MemGPTClassicFidelity()


__all__ = [
    "MEMGPT_CLASSIC_FIDELITY",
    "MEMGPT_CONTEXT_OVERFLOW_FIX",
    "MEMGPT_PAPER_ERA_ANCHOR",
    "MemGPTClassicFidelity",
]
