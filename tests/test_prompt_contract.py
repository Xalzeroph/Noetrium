from prompt_os_test_support import make_promoted_prompt_registry, promote_prompt_generation
import unittest
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity
from noetrium_platform.capabilities.model.request.prompt.runtime import PromptRegistry, build_prompt_request_contract, default_prompt_specs, verify_prompt_request_contract


class PromptContractTests(unittest.TestCase):
    def test_exact_request_identity_binds_atomic_prompt_generation_resolution(self):
        reg = make_promoted_prompt_registry(generation_id="g1")
        resolution = reg.resolve("planner.v6")
        bundle = resolution.bundle
        model = ImmutableModelIdentity("m","id","rev","sglang","1","bfloat16",None,262144)
        body = {"messages":[{"role":"system","content":bundle.text}],"temperature":bundle.temperature}
        c = build_prompt_request_contract(request_id="rq1", resolution=resolution, model=model, request_body=body)
        self.assertEqual(c.generation_id, "g1")
        verify_prompt_request_contract(c, resolution=resolution, model=model, request_body=body)
        with self.assertRaises(ValueError):
            verify_prompt_request_contract(c, resolution=resolution, model=model, request_body={**body,"temperature":0.9})

        promote_prompt_generation(reg, "g2", default_prompt_specs())
        with self.assertRaises(ValueError):
            verify_prompt_request_contract(c, resolution=reg.resolve("planner.v6"), model=model, request_body=body)

    def test_resolution_is_single_atomic_generation_bundle_cut(self):
        reg = make_promoted_prompt_registry(generation_id="g1")
        old = reg.resolve("planner.v6")
        promote_prompt_generation(reg, "g2", default_prompt_specs())
        new = reg.resolve("planner.v6")
        self.assertEqual(old.generation_id, "g1")
        self.assertEqual(new.generation_id, "g2")
        self.assertEqual(old.bundle.digest, new.bundle.digest)


if __name__ == "__main__": unittest.main()
