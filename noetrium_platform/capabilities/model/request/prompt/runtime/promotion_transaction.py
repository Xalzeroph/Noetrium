from __future__ import annotations

import time

from .active_pointer import ActivePromptPointer
from .generation_store import PromptGenerationManifest,PromptGenerationStore
from .promotion_contracts import PromptPromotionEvidence,PromptPromotionRecord
from .promotion_record_store import PromotionRecordStore
from .promotion_validation import PromptPromotionValidator
from .publication_common import PromptPublicationError


class PromptPromotionTransaction:
    """Crash-resumable qualification-record -> ACTIVE pointer transaction."""

    def __init__(
        self,
        *,
        generations:PromptGenerationStore,
        records:PromotionRecordStore,
        pointer:ActivePromptPointer,
        validator:PromptPromotionValidator,
    )->None:
        self.generations=generations
        self.records=records
        self.pointer=pointer
        self.validator=validator

    @staticmethod
    def _validate_existing_record(
        record:PromptPromotionRecord,
        manifest:PromptGenerationManifest,
        evidence:PromptPromotionEvidence,
    )->None:
        if record.generation_id!=manifest.generation_id:
            raise PromptPublicationError("promotion record generation identity mismatch")
        if record.generation_payload_sha256!=manifest.payload_sha256:
            raise PromptPublicationError("promotion record payload digest mismatch")
        if record.promotion_evidence_digest!=evidence.digest():
            raise PromptPublicationError(
                "generation promotion already exists with different qualification evidence"
            )

    def _resume(
        self,
        record:PromptPromotionRecord,
        manifest:PromptGenerationManifest,
        evidence:PromptPromotionEvidence,
    )->PromptPromotionRecord:
        self._validate_existing_record(record,manifest,evidence)
        active=self.pointer.read()
        if active==record.generation_id:
            return record
        if active!=record.previous_generation_id:
            raise PromptPublicationError(
                "cannot resume promotion: ACTIVE pointer advanced to a different generation"
            )
        self.pointer.write(record.generation_id)
        return record

    def execute(self,evidence:PromptPromotionEvidence)->PromptPromotionRecord:
        manifest,bundles=self.generations.load(evidence.generation_id)
        self.validator.validate(manifest,bundles,evidence)

        if self.records.exists(evidence.generation_id):
            return self._resume(
                self.records.load(evidence.generation_id),
                manifest,
                evidence,
            )

        previous=self.pointer.read()
        record=PromptPromotionRecord(
            evidence.generation_id,
            manifest.payload_sha256,
            evidence.digest(),
            previous,
            time.time(),
        )
        self.records.write_new(record)
        self.pointer.write(evidence.generation_id)
        return record
