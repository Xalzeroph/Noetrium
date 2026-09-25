from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .blocks import PromptBlock
from .runtime_contracts import ActivePromptBundle


@dataclass(frozen=True, slots=True)
class PromptBlockStat:
    kind: str
    chars: int
    bytes: int
    source_digest: str


@dataclass(frozen=True, slots=True)
class PromptRenderResult:
    text: str
    dynamic_digest: str
    block_kinds: tuple[str, ...]
    block_stats: tuple[PromptBlockStat, ...]
    compiled_chars: int
    compiled_bytes: int


class PromptRenderer:
    """Pure deterministic renderer over already-validated ordered blocks."""

    def render(
        self,
        bundle: ActivePromptBundle,
        ordered_blocks: tuple[PromptBlock, ...],
    ) -> PromptRenderResult:
        base = bundle.text.rstrip()
        base_bytes = base.encode("utf-8")
        parts = [base]
        # Final text is base + one terminal newline plus two separators per block.
        compiled_bytes = len(base_bytes) + 1
        digest = hashlib.sha256()
        stats: list[PromptBlockStat] = []
        block_kinds: list[str] = []
        for block in ordered_blocks:
            kind = block.kind.value
            kind_bytes = kind.encode("utf-8")
            source_digest_bytes = block.source_digest.encode("ascii")
            content = block.content
            content_bytes = content.encode("utf-8")
            stripped = content.strip()
            stripped_bytes = content_bytes if stripped == content else stripped.encode("utf-8")

            parts.append(f"[{kind}]\n{stripped}")
            compiled_bytes += 2 + len(kind_bytes) + 1 + len(stripped_bytes)
            digest.update(kind_bytes)
            digest.update(b"\0")
            digest.update(source_digest_bytes)
            digest.update(b"\0")
            digest.update(content_bytes)
            block_kinds.append(kind)
            stats.append(PromptBlockStat(kind, len(content), len(content_bytes), block.source_digest))

        text = "\n\n".join(parts) + "\n"
        return PromptRenderResult(
            text=text,
            dynamic_digest=digest.hexdigest(),
            block_kinds=tuple(block_kinds),
            block_stats=tuple(stats),
            compiled_chars=len(text),
            compiled_bytes=compiled_bytes,
        )
