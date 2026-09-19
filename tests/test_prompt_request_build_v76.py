from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from noetrium_platform.evidence.artifact.content.providers import DirectoryArtifactBlobStore
from noetrium_platform.capabilities.model.request.runtime import DirectoryModelRequestLedger, ReconstructableModelRequestRecorder
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity
from noetrium_platform.capabilities.model.request.prompt.runtime import (
    PromptBlock,
    PromptBlockKind,
    PromptCompilePipeline,
    PromptRegistry,
    PromptRequestBuildTransaction,
    default_block_policies,
    default_output_schemas,
    default_prompt_specs,
)


class PromptRequestBuildV76Tests(unittest.TestCase):
    def transaction(self):
        return PromptRequestBuildTransaction(PromptCompilePipeline())

    def recorder(self, root: Path):
        return ReconstructableModelRequestRecorder(
            DirectoryArtifactBlobStore(root / "blobs"),
            DirectoryModelRequestLedger(root / "requests"),
        )

    def context(self):
        return ExecutionContext(run_id="r76", trace_id="tr76", span_id="sp76", decision_cycle_id="dc76")

    def blocks(self):
        K=PromptBlockKind
        return (
            PromptBlock(K.TASK,"collect wood","d1",1),
            PromptBlock(K.VERIFIED_STATE,"inventory empty","d2",2),
            PromptBlock(K.TOOL_CATALOG,"mine/craft","d3",3),
        )

    def model(self):
        return ImmutableModelIdentity("m","id","rev","sglang","1","bfloat16",None,262144)

    def test_generation_switch_during_body_build_cannot_mix_request_identity(self):
        td=tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup); root=Path(td.name)
        registry=PromptRegistry(); registry.publish("g1",default_prompt_specs())

        def body_builder(resolution,compilation):
            self.assertEqual(resolution.generation_id,"g1")
            registry.publish("g2",default_prompt_specs())
            return {
                "messages":[{"role":"system","content":compilation.compiled.text}],
                "temperature":resolution.bundle.temperature,
            }

        bound=self.transaction().build(
            registry=registry,
            prompt_id="planner.v6",
            policy=default_block_policies()["planner"],
            blocks=self.blocks(),
            schemas=default_output_schemas(),
            request_id="rq76",
            context=self.context(),
            model=self.model(),
            model_requests=self.recorder(root),
            body_builder=body_builder,
        )
        self.assertEqual(registry.generation,"g2")
        self.assertEqual(bound.resolution.generation_id,"g1")
        self.assertEqual(bound.request_contract.generation_id,"g1")
        self.assertEqual(bound.execution_contract.generation_id,"g1")
        self.assertEqual(
            bound.request_contract.body_sha256,
            bound.execution_contract.request_body_sha256,
        )
        self.assertEqual(
            bound.execution_contract.request_body_sha256,
            bound.model_request.request_body.content_sha256,
        )
        with self.assertRaises(TypeError):
            bound.request_body["temperature"]=0.0
        with self.assertRaises(TypeError):
            bound.request_body["messages"][0]["content"]="tampered"

    def test_builder_owned_body_cannot_mutate_frozen_request_cut(self):
        td=tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup); root=Path(td.name)
        registry=PromptRegistry(); registry.publish("g1",default_prompt_specs())
        retained={}
        def body_builder(resolution,compilation):
            body={"messages":[{"role":"system","content":compilation.compiled.text}],"temperature":resolution.bundle.temperature}
            retained["body"]=body
            return body
        bound=self.transaction().build(
            registry=registry,prompt_id="planner.v6",policy=default_block_policies()["planner"],
            blocks=self.blocks(),schemas=default_output_schemas(),
            request_id="rq76-freeze",context=self.context(),model=self.model(),
            model_requests=self.recorder(root),body_builder=body_builder,
        )
        original=bound.request_body["messages"][0]["content"]
        retained["body"]["messages"][0]["content"]="caller-mutated"
        self.assertEqual(bound.request_body["messages"][0]["content"],original)
        with self.assertRaises(TypeError): bound.request_body["messages"][0]["content"]="direct-mutated"

    def test_non_dict_body_is_rejected_before_contract_creation(self):
        td=tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup); root=Path(td.name)
        registry=PromptRegistry(); registry.publish("g1",default_prompt_specs())
        with self.assertRaises(TypeError):
            self.transaction().build(
                registry=registry,
                prompt_id="planner.v6",
                policy=default_block_policies()["planner"],
                blocks=self.blocks(),
                schemas=default_output_schemas(),
                    request_id="rq76",
                context=self.context(),
                model=self.model(),
                model_requests=self.recorder(root),
                body_builder=lambda *_: "bad",
            )


if __name__=="__main__": unittest.main()
