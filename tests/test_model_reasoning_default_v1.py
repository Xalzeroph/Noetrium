from __future__ import annotations

import unittest

from noetrium_platform.capabilities.model.serving.provider import (
    ModelProviderRequestPlanner,
    NativeModelProviderProfileResolver,
    NativeModelProviderProtocolRegistry,
)


class ModelReasoningDefaultTests(unittest.TestCase):
    def _profile(self, engine: str = "vllm"):
        return NativeModelProviderProfileResolver().resolve(
            logical_model_name="Qwen3-8B",
            provider_model_name="Qwen3-8B",
            model_engine=engine,
        )

    @staticmethod
    def _body(**extra):
        return {
            "model": "Qwen3-8B",
            "messages": ({"role": "user", "content": "Return one action."},),
            "max_tokens": 32,
            **extra,
        }

    def test_vllm_defaults_thinking_off(self) -> None:
        plan = ModelProviderRequestPlanner().plan(
            self._profile(),
            self._body(),
        )
        self.assertEqual(
            plan.extra_body["chat_template_kwargs"],
            {"enable_thinking": False},
        )
        wire = NativeModelProviderProtocolRegistry().encode(plan)
        self.assertEqual(
            wire.body["chat_template_kwargs"],
            {"enable_thinking": False},
        )

    def test_vllm_merges_default_into_other_chat_template_kwargs(self) -> None:
        plan = ModelProviderRequestPlanner().plan(
            self._profile(),
            self._body(chat_template_kwargs={"foo": "bar"}),
        )
        self.assertEqual(
            plan.extra_body["chat_template_kwargs"],
            {"foo": "bar", "enable_thinking": False},
        )

    def test_explicit_thinking_true_overrides_platform_default(self) -> None:
        plan = ModelProviderRequestPlanner().plan(
            self._profile(),
            self._body(chat_template_kwargs={"enable_thinking": True}),
        )
        self.assertEqual(
            plan.extra_body["chat_template_kwargs"],
            {"enable_thinking": True},
        )

    def test_explicit_reasoning_control_does_not_get_conflicting_default(self) -> None:
        plan = ModelProviderRequestPlanner().plan(
            self._profile(),
            self._body(reasoning_effort="high"),
        )
        self.assertEqual(plan.standard_body["reasoning_effort"], "high")
        self.assertNotIn("chat_template_kwargs", plan.extra_body)

    def test_non_chat_template_provider_is_unchanged(self) -> None:
        plan = ModelProviderRequestPlanner().plan(
            self._profile("openai"),
            self._body(),
        )
        self.assertNotIn("chat_template_kwargs", plan.extra_body)


if __name__ == "__main__":
    unittest.main()
