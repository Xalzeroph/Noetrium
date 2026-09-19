from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256


class StormWikiStage(StrEnum):
    KNOWLEDGE_CURATION = "knowledge_curation"
    OUTLINE_GENERATION = "outline_generation"
    ARTICLE_GENERATION = "article_generation"
    ARTICLE_POLISHING = "article_polishing"


STORM_WIKI_STAGE_ORDER = (
    StormWikiStage.KNOWLEDGE_CURATION,
    StormWikiStage.OUTLINE_GENERATION,
    StormWikiStage.ARTICLE_GENERATION,
    StormWikiStage.ARTICLE_POLISHING,
)

STORM_WIKI_STAGE_DEPENDENCIES = {
    StormWikiStage.KNOWLEDGE_CURATION: (),
    StormWikiStage.OUTLINE_GENERATION: (StormWikiStage.KNOWLEDGE_CURATION,),
    StormWikiStage.ARTICLE_GENERATION: (
        StormWikiStage.KNOWLEDGE_CURATION,
        StormWikiStage.OUTLINE_GENERATION,
    ),
    StormWikiStage.ARTICLE_POLISHING: (StormWikiStage.ARTICLE_GENERATION,),
}

STORM_WIKI_STAGE_OUTPUTS = {
    StormWikiStage.KNOWLEDGE_CURATION: (
        "conversation_log.json",
        "raw_search_results.json",
    ),
    StormWikiStage.OUTLINE_GENERATION: (
        "storm_gen_outline.txt",
        "direct_gen_outline.txt",
    ),
    StormWikiStage.ARTICLE_GENERATION: (
        "storm_gen_article.txt",
        "url_to_info.json",
    ),
    StormWikiStage.ARTICLE_POLISHING: ("storm_gen_article_polished.txt",),
}


@dataclass(frozen=True, slots=True)
class StormWikiStageReceipt:
    """Downstream semantic receipt for one completed paper-defined STORM stage."""

    stage: StormWikiStage
    output_bundle_digest: str
    dependency_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.stage, StormWikiStage):
            raise TypeError("STORM stage receipt requires StormWikiStage")
        require_sha256(self.output_bundle_digest, "STORM output_bundle_digest")
        if not isinstance(self.dependency_digests, tuple):
            raise TypeError("STORM dependency digests must be a tuple")
        for digest in self.dependency_digests:
            require_sha256(digest, "STORM dependency digest")
        expected_dependency_count = len(STORM_WIKI_STAGE_DEPENDENCIES[self.stage])
        if len(self.dependency_digests) != expected_dependency_count:
            raise ValueError("STORM stage receipt dependency count does not match paper pipeline")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class StormWikiPipelineState:
    """Immutable method state for resuming the paper pipeline from durable stage outputs."""

    topic: str
    receipts: tuple[StormWikiStageReceipt, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.topic, str) or not self.topic.strip() or self.topic != self.topic.strip():
            raise ValueError("STORM topic must be canonical non-empty text")
        if not isinstance(self.receipts, tuple) or any(
            not isinstance(receipt, StormWikiStageReceipt) for receipt in self.receipts
        ):
            raise TypeError("STORM pipeline receipts must be typed stage receipts")
        stages = tuple(receipt.stage for receipt in self.receipts)
        if len(set(stages)) != len(stages):
            raise ValueError("STORM pipeline cannot contain duplicate completed stages")
        expected_prefix = STORM_WIKI_STAGE_ORDER[: len(stages)]
        if stages != expected_prefix:
            raise ValueError("STORM completed stages must form the canonical dependency prefix")
        receipts_by_stage = {receipt.stage: receipt for receipt in self.receipts}
        for receipt in self.receipts:
            expected_digests = tuple(
                receipts_by_stage[dependency].output_bundle_digest
                for dependency in STORM_WIKI_STAGE_DEPENDENCIES[receipt.stage]
            )
            if receipt.dependency_digests != expected_digests:
                raise ValueError("STORM stage receipt is not bound to exact dependency outputs")

    @property
    def next_stage(self) -> StormWikiStage | None:
        if len(self.receipts) == len(STORM_WIKI_STAGE_ORDER):
            return None
        return STORM_WIKI_STAGE_ORDER[len(self.receipts)]

    def append(self, receipt: StormWikiStageReceipt) -> "StormWikiPipelineState":
        if self.next_stage is None:
            raise ValueError("STORM pipeline is already complete")
        if receipt.stage is not self.next_stage:
            raise ValueError("STORM stage cannot run before its dependencies")
        return StormWikiPipelineState(self.topic, self.receipts + (receipt,))


__all__ = [
    "STORM_WIKI_STAGE_DEPENDENCIES",
    "STORM_WIKI_STAGE_ORDER",
    "STORM_WIKI_STAGE_OUTPUTS",
    "StormWikiPipelineState",
    "StormWikiStage",
    "StormWikiStageReceipt",
]
