from prompt_os_test_support import make_prompt_registry
from pathlib import Path
import tempfile
import unittest

from noetrium_platform.capabilities.model.request.prompt.runtime import DurablePromptRegistry, PromptPromotionEvidence, PromptPublicationError, PromptQualification, default_block_policies, default_output_schemas, default_prompt_specs

MODEL=("m","rev","sglang","1","bfloat16",None,262144,"tok")
SUITE="c"*64
OBJ="d"*64

def evidence(manifest,*,qualified=True,model=MODEL):
    roles={s.bundle_digest():s.role for s in default_prompt_specs()}
    qs=tuple(PromptQualification(SUITE,d,roles[d],model,1,1 if qualified else 0,1,1 if qualified else 0,True) for _,d in manifest.bundle_digests)
    return PromptPromotionEvidence(manifest.generation_id,manifest.payload_sha256,SUITE,qs,model,OBJ,1.0)

class PromptPromotionV24Tests(unittest.TestCase):
    def test_stage_does_not_change_active(self):
        with tempfile.TemporaryDirectory() as td:
            r=make_prompt_registry(Path(td)); m=r.stage("g1",default_prompt_specs(),default_block_policies(),default_output_schemas())
            self.assertFalse((Path(td)/"ACTIVE").exists())
            with self.assertRaises(PromptPublicationError): r.load_active()

    def test_promotion_requires_every_bundle_qualified(self):
        with tempfile.TemporaryDirectory() as td:
            r=make_prompt_registry(Path(td)); m=r.stage("g1",default_prompt_specs(),default_block_policies(),default_output_schemas())
            bad=evidence(m,qualified=False)
            with self.assertRaises(PromptPublicationError): r.promote(bad)
            self.assertFalse((Path(td)/"ACTIVE").exists())

    def test_model_identity_drift_blocks_promotion(self):
        with tempfile.TemporaryDirectory() as td:
            r=make_prompt_registry(Path(td)); m=r.stage("g1",default_prompt_specs(),default_block_policies(),default_output_schemas()); ev=evidence(m)
            wrong=PromptPromotionEvidence(ev.generation_id,ev.generation_payload_sha256,ev.canary_suite_digest,ev.qualifications,("other",),ev.objective_evidence_digest,ev.created_at)
            with self.assertRaises(PromptPublicationError): r.promote(wrong)

    def test_explicit_promotion_creates_record_and_active_no_auto_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); r=make_prompt_registry(root); m=r.stage("g1",default_prompt_specs(),default_block_policies(),default_output_schemas()); rec=r.promote(evidence(m))
            self.assertEqual((root/"ACTIVE").read_text().strip(),"g1"); self.assertTrue((root/"promotions"/"g1.json").exists()); self.assertIsNone(rec.previous_generation_id)
            p=root/"generations"/"g1"/"generation.json"; p.write_text(p.read_text().replace("persistent open-world","tampered open-world",1))
            with self.assertRaises(PromptPublicationError): r.load_active()
            self.assertEqual((root/"ACTIVE").read_text().strip(),"g1")

    def test_direct_publish_path_is_forbidden(self):
        with tempfile.TemporaryDirectory() as td:
            r=make_prompt_registry(Path(td))
            with self.assertRaises(PromptPublicationError): r.publish("g",default_prompt_specs(),default_block_policies(),default_output_schemas())

if __name__=='__main__': unittest.main()
