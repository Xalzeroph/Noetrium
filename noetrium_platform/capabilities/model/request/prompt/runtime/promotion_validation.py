from __future__ import annotations
from .generation_store import PromptGenerationManifest
from .publication_common import PromptPublicationError
from .runtime import ActivePromptBundle

class PromptPromotionValidator:
    def validate(self,manifest:PromptGenerationManifest,bundles:tuple[ActivePromptBundle,...],evidence)->None:
        if manifest.payload_sha256!=evidence.generation_payload_sha256: raise PromptPublicationError("promotion evidence/generation digest mismatch")
        if len(evidence.objective_evidence_digest)!=64: raise PromptPublicationError("objective qualification evidence digest is required")
        q_by_digest={q.prompt_digest:q for q in evidence.qualifications}
        if len(q_by_digest)!=len(evidence.qualifications): raise PromptPublicationError("duplicate prompt qualification")
        expected={bundle.digest:bundle for bundle in bundles}
        if set(q_by_digest)!=set(expected): raise PromptPublicationError("qualification coverage must exactly match generation bundles")
        for digest,bundle in expected.items():
            q=q_by_digest[digest]
            if not q.qualified: raise PromptPublicationError(f"prompt not qualified: {bundle.prompt_id}")
            if q.role!=bundle.role or q.suite_digest!=evidence.canary_suite_digest or q.model_resume_key!=evidence.model_resume_key: raise PromptPublicationError(f"qualification identity drift: {bundle.prompt_id}")
