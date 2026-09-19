from __future__ import annotations

import unittest

from noetrium_platform.capabilities.model.request.prompt.runtime import (
    PromptBlock,
    PromptBlockKind,
    PromptCompilePipeline,
    PromptRegistry,
    default_block_policies,
    default_output_schemas,
    default_prompt_specs,
)


class PromptCompilePipelineV75Tests(unittest.TestCase):
    def pipeline(self) -> PromptCompilePipeline:
        return PromptCompilePipeline()

    def planner(self):
        registry = PromptRegistry()
        registry.publish("g75", default_prompt_specs())
        K = PromptBlockKind
        blocks = (
            PromptBlock(K.TASK, "collect wood", "d1", 1),
            PromptBlock(K.VERIFIED_STATE, "inventory empty", "d2", 2),
            PromptBlock(K.TOOL_CATALOG, "mine/craft", "d3", 3),
        )
        return registry.resolve("planner.v6"), blocks

    def test_pipeline_binds_generation_render_and_schema_without_model_budget_authority(self):
        resolution, blocks = self.planner()
        receipt = self.pipeline().compile(
            resolution=resolution,
            policy=default_block_policies()["planner"],
            blocks=blocks,
            schemas=default_output_schemas(),
        )
        self.assertEqual(receipt.generation_id, "g75")
        self.assertEqual(receipt.prompt_id, "planner.v6")
        self.assertEqual(receipt.compiled.block_kinds, ("task", "verified_state", "tool_catalog"))
        self.assertEqual(len(receipt.schema_digest), 64)
        self.assertFalse(hasattr(receipt, "budget"))

    def test_compile_preserves_required_blocks_without_silent_degradation(self):
        resolution, blocks = self.planner()
        original = tuple((b.kind, b.content, b.source_digest, b.sequence) for b in blocks)
        receipt = self.pipeline().compile(
            resolution=resolution,
            policy=default_block_policies()["planner"],
            blocks=blocks,
            schemas=default_output_schemas(),
        )
        self.assertEqual(
            tuple((b.kind, b.content, b.source_digest, b.sequence) for b in blocks),
            original,
        )
        self.assertEqual(receipt.compiled.block_kinds, ("task", "verified_state", "tool_catalog"))

    def test_forbidden_block_fails_in_validation_instead_of_being_ignored(self):
        resolution, blocks = self.planner()
        K = PromptBlockKind
        with self.assertRaises(ValueError):
            self.pipeline().compile(
                resolution=resolution,
                policy=default_block_policies()["planner"],
                blocks=blocks + (PromptBlock(K.FAILURE_EVIDENCE, "x", "bad", 4),),
                schemas=default_output_schemas(),
            )


if __name__ == "__main__":
    unittest.main()
