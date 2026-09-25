from __future__ import annotations

from prompt_os_test_support import make_prompt_registry
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from noetrium_platform.capabilities.model.request.prompt.runtime import (
    DurablePromptRegistry,
    PromptPublicationError,
    PromptPromotionEvidence,
    default_block_policies,
    default_output_schemas,
    default_prompt_specs,
)
from noetrium_platform.capabilities.model.request.prompt.runtime.qualification import PromptQualification


MODEL=("m","rev","sglang","1","bfloat16",None,262144,"tok")
SUITE="a"*64

def evidence(manifest,objective="d"*64):
    roles={s.bundle_digest():s.role for s in default_prompt_specs()}
    quals=tuple(
        PromptQualification(
            SUITE,
            digest,
            roles[digest],
            MODEL,
            1,
            1,
            1,
            1,
            True,
        )
        for _,digest in manifest.bundle_digests
    )
    return PromptPromotionEvidence(
        manifest.generation_id,
        manifest.payload_sha256,
        SUITE,
        quals,
        MODEL,
        objective,
        1.0,
    )


class PromptPromotionRecoveryV71Tests(unittest.TestCase):
    def test_record_durable_active_write_failure_resumes_without_new_record(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            reg=make_prompt_registry(root)
            manifest=reg.stage(
                "g1",
                default_prompt_specs(),
                default_block_policies(),
                default_output_schemas(),
            )
            ev=evidence(manifest)
            store=reg.promotion_store

            with mock.patch.object(
                store.pointer,
                "write",
                side_effect=OSError("power loss after promotion record"),
            ):
                with self.assertRaises(OSError):
                    store.promote(ev)

            record_path=root/"promotions"/"g1.json"
            self.assertTrue(record_path.exists())
            first_bytes=record_path.read_bytes()
            self.assertFalse((root/"ACTIVE").exists())

            resumed=store.promote(ev)
            self.assertEqual((root/"ACTIVE").read_text().strip(),"g1")
            self.assertEqual(record_path.read_bytes(),first_bytes)
            self.assertEqual(resumed.generation_id,"g1")

    def test_existing_record_with_different_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            reg=make_prompt_registry(root)
            manifest=reg.stage(
                "g1",
                default_prompt_specs(),
                default_block_policies(),
                default_output_schemas(),
            )
            ev=evidence(manifest)
            store=reg.promotion_store

            with mock.patch.object(store.pointer,"write",side_effect=OSError("cut")):
                with self.assertRaises(OSError):
                    store.promote(ev)

            changed=evidence(manifest,objective="e"*64)
            with self.assertRaises(PromptPublicationError):
                store.promote(changed)
            self.assertFalse((root/"ACTIVE").exists())

    def test_resume_refuses_to_roll_active_pointer_back(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            reg=make_prompt_registry(root)
            m1=reg.stage("g1",default_prompt_specs(),default_block_policies(),default_output_schemas())
            with mock.patch.object(reg.promotion_store.pointer,"write",side_effect=OSError("cut")):
                with self.assertRaises(OSError):
                    reg.promotion_store.promote(evidence(m1))

            # Simulate a distinct, later authority decision; stale g1 retry must not overwrite it.
            (root/"ACTIVE").write_text("g2\n",encoding="utf-8")
            with self.assertRaises(PromptPublicationError):
                reg.promotion_store.promote(evidence(m1))
            self.assertEqual((root/"ACTIVE").read_text().strip(),"g2")


if __name__=="__main__":
    unittest.main()
