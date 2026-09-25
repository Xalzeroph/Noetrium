from __future__ import annotations

from pathlib import Path

from .active_pointer import ActivePromptPointer
from .generation_store import PromptGenerationManifest, PromptGenerationStore
from .promotion_contracts import PromptPromotionEvidence, PromptPromotionRecord
from .promotion_record_store import PromotionRecordStore
from .promotion_transaction import PromptPromotionTransaction
from .promotion_validation import PromptPromotionValidator
from .publication_common import PromptPublicationError, PromptPublicationLease
from .runtime import ActivePromptBundle
from noetrium_platform.capabilities.model.request.prompt.api import ActivePromptVerificationEvidence, PromptVerificationIntegrityError


class PromptPromotionStore:
    """Promotion façade over explicitly supplied record/pointer/generation authorities."""

    def __init__(
        self,
        *,
        generation_store: PromptGenerationStore,
        records: PromotionRecordStore,
        pointer: ActivePromptPointer,
        lock_path: Path,
    ) -> None:
        self.generation_store = generation_store
        self.lock_path = lock_path
        self.validator = PromptPromotionValidator()
        self.records = records
        self.pointer = pointer
        self.transaction = PromptPromotionTransaction(
            generations=generation_store,
            records=records,
            pointer=pointer,
            validator=self.validator,
        )

    def promote(self, evidence: PromptPromotionEvidence) -> PromptPromotionRecord:
        with PromptPublicationLease(self.lock_path):
            return self.transaction.execute(evidence)

    def _validate_evidence(
        self,
        manifest: PromptGenerationManifest,
        bundles: tuple[ActivePromptBundle, ...],
        evidence: PromptPromotionEvidence,
    ) -> None:
        self.validator.validate(manifest, bundles, evidence)

    def load_active(self) -> tuple[PromptGenerationManifest, tuple[ActivePromptBundle, ...]]:
        active = self.pointer.read()
        if active is None:
            raise PromptPublicationError("no ACTIVE prompt generation")
        return self.generation_store.load(active)

    def read_active_verification_evidence(self) -> ActivePromptVerificationEvidence:
        """Export stable read-only evidence without exposing publication storage topology."""
        generation_id = self.pointer.read()
        if generation_id is None:
            raise PromptVerificationIntegrityError("no ACTIVE prompt generation")
        generation, _bundles = self.generation_store.load(generation_id)
        record = self.records.load(generation_id)
        if record.generation_payload_sha256 != generation.payload_sha256:
            raise PromptVerificationIntegrityError("prompt promotion record/generation payload drift")
        return ActivePromptVerificationEvidence(
            generation_id=generation_id,
            generation_payload_sha256=generation.payload_sha256,
            promotion_evidence_digest=record.promotion_evidence_digest,
        )


__all__ = ["PromptPromotionEvidence", "PromptPromotionRecord", "PromptPromotionStore"]
