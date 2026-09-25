import unittest
from noetrium_platform.capabilities.model.request.prompt.runtime import default_prompt_specs
from noetrium_platform.capabilities.model.request.prompt.runtime.role_specs import planner_prompt_spec, semantic_prompt_spec, meta_prompt_spec, diagnostic_prompt_spec

class PromptRoleSplitV30Tests(unittest.TestCase):
    def test_aggregator_is_exact_role_composition(self):
        expected=(planner_prompt_spec(),semantic_prompt_spec(),meta_prompt_spec(),diagnostic_prompt_spec())
        actual=default_prompt_specs()
        self.assertEqual([x.bundle_digest() for x in actual],[x.bundle_digest() for x in expected])
        self.assertEqual([x.role for x in actual],["planner","semantic","meta","diagnostic"])

if __name__ == "__main__": unittest.main()
