from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.composition.prompt_registry import build_durable_prompt_registry
from noetrium_platform.capabilities.model.request.prompt.runtime import (
    PromptPromotionEvidence,
    PromptQualification,
    default_block_policies,
    default_output_schemas,
    default_prompt_specs,
)


MODEL = ("m", "rev", "sglang", "1", "bfloat16", None, 262144, "tok")
SUITE = "c" * 64
OBJECTIVE = "d" * 64


def _evidence(manifest):
    roles = {spec.bundle_digest(): spec.role for spec in default_prompt_specs()}
    qualifications = tuple(
        PromptQualification(SUITE, digest, roles[digest], MODEL, 1, 1, 1, 1, True)
        for _, digest in manifest.bundle_digests
    )
    return PromptPromotionEvidence(
        manifest.generation_id,
        manifest.payload_sha256,
        SUITE,
        qualifications,
        MODEL,
        OBJECTIVE,
        1.0,
    )


class PromptStorageDecouplingV176Tests(unittest.TestCase):
    def test_generation_records_active_pointer_and_lock_can_use_independent_roots(self) -> None:
        with (
            TemporaryDirectory() as generation_td,
            TemporaryDirectory() as promotion_td,
            TemporaryDirectory() as active_td,
            TemporaryDirectory() as lock_td,
        ):
            generations = Path(generation_td) / "immutable"
            promotions = Path(promotion_td) / "records"
            active = Path(active_td) / "control" / "ACTIVE"
            lock = Path(lock_td) / "leases" / "publication.lock"
            active.parent.mkdir(parents=True, exist_ok=True)

            registry = build_durable_prompt_registry(
                generations_root=generations,
                promotion_records_root=promotions,
                active_pointer_path=active,
                publication_lock_path=lock,
            )
            manifest = registry.stage(
                "g1", default_prompt_specs(), default_block_policies(), default_output_schemas()
            )
            registry.promote(_evidence(manifest))
            loaded, bundles = registry.load_active()

            self.assertEqual(loaded, manifest)
            self.assertTrue((generations / "g1" / "generation.json").exists())
            self.assertTrue((promotions / "g1.json").exists())
            self.assertEqual(active.read_text(encoding="utf-8").strip(), "g1")
            self.assertTrue(lock.exists())
            self.assertEqual(len(bundles), len(default_prompt_specs()))


if __name__ == "__main__":
    unittest.main()
