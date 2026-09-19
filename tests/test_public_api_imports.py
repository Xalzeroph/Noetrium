import importlib
import unittest


class PublicAPIImportTests(unittest.TestCase):
    def test_core_public_packages_import(self):
        import noetrium_platform.evidence.observability.telemetry as telemetry
        import noetrium_platform.infrastructure.reliability.forensics as forensics
        import noetrium_platform.capabilities.model.serving as model_serving
        import noetrium_platform.product.operator as operator
        import noetrium_platform.capabilities.model.request.prompt.runtime as prompt_runtime
        for module in (telemetry, forensics, model_serving, operator, prompt_runtime):
            self.assertIsNotNone(module)

    def test_public_contract_and_extension_layers_are_discoverable(self):
        import components
        import noetrium
        import components.reference
        import noetrium.contracts
        import orchestration
        from noetrium.contracts import AgentGoal, JsonValue, ResearchMethodHost
        from orchestration.multi_agent import MultiAgentRuntime

        self.assertEqual(noetrium.__all__, ["__version__"])
        self.assertIsNotNone(AgentGoal)
        self.assertIsNotNone(JsonValue)
        self.assertIsNotNone(ResearchMethodHost)
        self.assertIsNotNone(components.reference)
        self.assertIsNotNone(MultiAgentRuntime)

    def test_removed_extension_aliases_are_not_importable(self):
        for module_name in (
            "noetrium" + suffix
            for suffix in (".adapters", ".components", ".orchestration")
        ):
            with self.assertRaises(ModuleNotFoundError):
                importlib.import_module(module_name)

    def test_system_descriptor_uses_package_boundaries(self):
        from noetrium_platform.foundation.governance.system_registry.api import (
            SystemDescriptor,
            SystemIdentity,
            SystemLayer,
            SystemNodeKind,
        )

        with self.assertRaises(ValueError):
            SystemDescriptor(
                identity=SystemIdentity("platform"),
                layer=SystemLayer.PLATFORM,
                package_prefix="noetrium_platform_shadow",
                node_kind=SystemNodeKind.PROVIDER,
            )


if __name__ == '__main__':
    unittest.main()
