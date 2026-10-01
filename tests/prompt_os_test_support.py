from __future__ import annotations

from pathlib import Path
import tempfile

from noetrium_platform.capabilities.model.request.prompt.runtime import (
    OutputSchemaRegistry,
    OutputSchemaSpec,
    PromptBlockPolicy,
    PromptPromotionEvidence,
    PromptQualification,
    PromptSpec,
    default_prompt_specs,
)
from noetrium_platform.composition.prompt_registry import build_prompt_registry

_TEST_MODEL = (
    "test-model",
    "test-revision",
    "test-engine",
    "1",
    "bfloat16",
    None,
    262144,
    "test-tokenizer",
)
_TEST_SUITE_DIGEST = "c" * 64
_TEST_OBJECTIVE_DIGEST = "d" * 64


def make_prompt_registry(root: Path):
    return build_prompt_registry(
        generations_root=root / "generations",
        promotion_records_root=root / "promotions",
        active_pointer_path=root / "ACTIVE",
        publication_lock_path=root / ".publication.lock",
    )


def _publication_inputs(
    specs: tuple[PromptSpec, ...],
) -> tuple[dict[str, PromptBlockPolicy], OutputSchemaRegistry]:
    policies = {
        role: PromptBlockPolicy(role, frozenset(), frozenset(), ())
        for role in sorted({spec.role for spec in specs})
    }
    schemas = OutputSchemaRegistry(tuple(
        OutputSchemaSpec(
            schema_id,
            "test",
            {"type": "object", "additionalProperties": True},
        )
        for schema_id in sorted({spec.output_schema for spec in specs})
    ))
    return policies, schemas


def promote_prompt_generation(
    registry,
    generation_id: str,
    specs: tuple[PromptSpec, ...],
):
    policies, schemas = _publication_inputs(specs)
    manifest = registry.stage(generation_id, specs, policies, schemas)
    roles = {spec.bundle_digest(): spec.role for spec in specs}
    qualifications = tuple(
        PromptQualification(
            _TEST_SUITE_DIGEST,
            digest,
            roles[digest],
            _TEST_MODEL,
            1,
            1,
            1,
            1,
            True,
        )
        for _prompt_id, digest in manifest.bundle_digests
    )
    registry.promote(PromptPromotionEvidence(
        manifest.generation_id,
        manifest.payload_sha256,
        _TEST_SUITE_DIGEST,
        qualifications,
        _TEST_MODEL,
        _TEST_OBJECTIVE_DIGEST,
        1.0,
    ))
    return manifest


def make_promoted_prompt_registry(
    *,
    generation_id: str = "test-generation",
    specs: tuple[PromptSpec, ...] | None = None,
    root: Path | None = None,
):
    actual_root = root or Path(tempfile.mkdtemp(prefix="noetrium-prompt-test-"))
    registry = make_prompt_registry(actual_root)
    promote_prompt_generation(
        registry,
        generation_id,
        default_prompt_specs() if specs is None else specs,
    )
    return registry


__all__ = [
    "make_prompt_registry",
    "make_promoted_prompt_registry",
    "promote_prompt_generation",
]
