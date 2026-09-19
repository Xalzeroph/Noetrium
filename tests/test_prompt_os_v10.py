from prompt_os_test_support import make_prompt_registry
from pathlib import Path
import json
import hashlib
import tempfile

from noetrium_platform.capabilities.model.request.prompt.runtime.generation_codec import decode_generation, encode_generation
import unittest

from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity, canonical_bytes
from noetrium_platform.capabilities.model.request.prompt.runtime import (
    CanaryObservation, CanarySuite, DurablePromptRegistry, OutputSchemaSpec, PromptBlock,
    PromptBlockKind, PromptCanary, PromptCompiler,
    PromptPublicationError, PromptPromotionEvidence, PromptQualification, PromptRegistry, build_execution_contract, default_block_policies,
    default_output_schemas, default_prompt_specs, evaluate_canaries,
)


class PromptOSV10Tests(unittest.TestCase):
    def _bundle(self, prompt_id="planner.v6"):
        r=PromptRegistry(); r.publish("g10",default_prompt_specs()); return r.get(prompt_id)

    def test_durable_publication_rejects_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); store=make_prompt_registry(root)
            m=store.stage("gen_1",default_prompt_specs(),default_block_policies(),default_output_schemas())
            model_key=("id","rev","sglang","1","bfloat16",None,262144,None); suite_digest="a"*64
            role_by={s.bundle_digest():s.role for s in default_prompt_specs()}
            quals=tuple(PromptQualification(suite_digest,d,role_by[d],model_key,1,1,1,1,True) for _,d in m.bundle_digests)
            store.promote(PromptPromotionEvidence("gen_1",m.payload_sha256,suite_digest,quals,model_key,"b"*64,1.0))
            loaded,bundles=store.load_active(); self.assertEqual(loaded.payload_sha256,m.payload_sha256); self.assertEqual(len(bundles),4)
            p=root/"generations"/"gen_1"/"generation.json"; text=p.read_text(); p.write_text(text.replace("persistent open-world","tampered open-world",1))
            with self.assertRaises(PromptPublicationError): store.load_active()

    def test_execution_contract_binds_dynamic_schema_model_and_generation(self):
        r=PromptRegistry(); r.publish("g10",default_prompt_specs()); b=r.get("planner.v6"); K=PromptBlockKind
        blocks=(PromptBlock(K.TASK,"task","a",1),PromptBlock(K.VERIFIED_STATE,"state","b",2),PromptBlock(K.TOOL_CATALOG,"tools","c",3))
        compiled=PromptCompiler().compile(b,default_block_policies()["planner"],blocks)
        schema=default_output_schemas().require(b.output_schema)
        model=ImmutableModelIdentity("m","id","rev","sglang","1","bfloat16",None,262144)
        from noetrium_platform.capabilities.model.request.prompt.runtime import PromptCompilationReceipt
        receipt=PromptCompilationReceipt("g10",b.prompt_id,b.digest,schema.schema_id,schema.digest(),compiled)
        c=build_execution_contract(request_id="r",compilation=receipt,resolution=r.resolve("planner.v6"),model=model,request_body={"messages":[]})
        self.assertEqual(c.dynamic_digest,compiled.dynamic_digest); self.assertEqual(c.schema_digest,schema.digest()); self.assertEqual(c.model_resume_key,model.resume_key())

    def test_canary_qualification_rejects_mixed_model_identity(self):
        suite=CanarySuite("s",(PromptCanary("a","planner",True,"i","o"),PromptCanary("b","planner",False,"j","o")),"v")
        obs=(CanaryObservation("a","p",("model1",),True,True),CanaryObservation("b","p",("model2",),True,True))
        q=evaluate_canaries(suite,"planner","p",obs)
        self.assertFalse(q.qualified); self.assertFalse(q.complete)

    def test_v6_role_prompts_preserve_authority_boundaries(self):
        specs={s.role:s for s in default_prompt_specs()}
        self.assertIn("Verified current state",specs["planner"].compile())
        self.assertIn("NO_EDIT, CREATE, RETIRE, SPLIT, MERGE",specs["meta"].compile())
        self.assertIn("Never use verifier-private, evaluation-private, audit-private",specs["semantic"].compile())
        self.assertIn("Temporal proximity alone is never causality",specs["diagnostic"].compile())

    def test_output_schema_is_deeply_immutable_after_digest_binding(self):
        raw={"type":"object","required":["x"],"properties":{"x":{"type":"string"}}}
        spec=OutputSchemaSpec("immutable","1",raw)
        digest=spec.digest()
        raw["type"]="array"
        raw["required"].append("y")
        self.assertEqual(spec.schema["type"],"object")
        self.assertEqual(spec.schema["required"],("x",))
        self.assertEqual(spec.digest(),digest)
        with self.assertRaises(TypeError): spec.schema["type"]="array"
        with self.assertRaises((TypeError, AttributeError)): spec.schema["required"].append("y")
        with self.assertRaises(TypeError): dict.__setitem__(spec.schema,"type","bypassed")
        with self.assertRaises(TypeError): list.append(spec.schema["required"],"bypassed")
        recursive={}
        recursive["self"]=recursive
        from noetrium_platform.foundation.kernel.kernel import CanonicalEncodingError
        with self.assertRaisesRegex(CanonicalEncodingError,"cyclic"):
            OutputSchemaSpec("recursive","1",recursive)

    def test_encoded_generation_payload_cannot_drift_from_payload_hash(self):
        encoded=encode_generation("immutable_gen",default_prompt_specs(),default_block_policies(),default_output_schemas())
        digest=hashlib.sha256(canonical_bytes(encoded.payload)).hexdigest()
        self.assertEqual(digest,encoded.payload_sha256)
        with self.assertRaises(TypeError): encoded.payload["generation_id"]="other"
        with self.assertRaises(TypeError): encoded.payload["bundles"][0]["text"]="tampered"
        self.assertEqual(hashlib.sha256(canonical_bytes(encoded.payload)).hexdigest(),encoded.payload_sha256)
        decoded_digest,_,decoded_payload=decode_generation(encoded.envelope_bytes.decode("utf-8"),"immutable_gen")
        self.assertEqual(decoded_digest,encoded.payload_sha256)
        with self.assertRaises(TypeError): decoded_payload["generation_id"]="tampered"
        with self.assertRaises(TypeError): decoded_payload["bundles"][0]["text"]="tampered"

if __name__ == '__main__': unittest.main()
