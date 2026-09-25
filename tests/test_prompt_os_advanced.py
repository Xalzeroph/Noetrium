import unittest
from noetrium_platform.capabilities.model.request.prompt.runtime import (
    CanaryObservation, CanarySuite, PromptBlock, PromptBlockKind, PromptCanary, PromptCompiler,
    PromptRegistry, default_block_policies, default_prompt_specs, evaluate_canaries,
    PromptOutcomeLink, summarize_outcomes,
)

class PromptOSAdvancedTests(unittest.TestCase):
    def test_planner_compiler_enforces_block_policy(self):
        r=PromptRegistry(); r.publish("g",default_prompt_specs()); b=r.get("planner.v6")
        K=PromptBlockKind
        blocks=(PromptBlock(K.TASK,"get wood","a",1),PromptBlock(K.VERIFIED_STATE,"inv empty","b",2),PromptBlock(K.TOOL_CATALOG,"mine/craft","c",3))
        c=PromptCompiler().compile(b,default_block_policies()["planner"],blocks)
        self.assertEqual(c.block_kinds,("task","verified_state","tool_catalog"))
        with self.assertRaises(ValueError):
            PromptCompiler().compile(b,default_block_policies()["planner"],blocks+(PromptBlock(K.FAILURE_EVIDENCE,"x","d",4),))

    def test_meta_cannot_receive_task_or_tools(self):
        r=PromptRegistry(); r.publish("g",default_prompt_specs()); b=r.get("meta.v6"); K=PromptBlockKind
        with self.assertRaises(ValueError):
            PromptCompiler().compile(b,default_block_policies()["meta"],(PromptBlock(K.ARCHITECTURE_OBSERVATION,"aor","x",1),PromptBlock(K.TOOL_CATALOG,"tools","y",2)))

    def test_canary_qualification_requires_complete_exact_digest(self):
        suite=CanarySuite("s",(PromptCanary("c1","planner",True,"i","schema"),PromptCanary("c2","planner",False,"j","schema")),"eval1")
        q=evaluate_canaries(suite,"planner","p",(CanaryObservation("c1","p",("m",),True,True),CanaryObservation("c2","p",("m",),True,True)))
        self.assertTrue(q.qualified)
        q2=evaluate_canaries(suite,"planner","p",(CanaryObservation("c1","p",("m",),True,True),))
        self.assertFalse(q2.qualified)

    def test_outcome_summary_never_claims_causality(self):
        s=summarize_outcomes("p",(PromptOutcomeLink("r","p","t","d",None,True,True,1.0,0),))
        self.assertFalse(s.effect_claim_authorized)

if __name__=="__main__": unittest.main()
