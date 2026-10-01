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

    def test_unified_downstream_api_is_only_top_level_research_os(self):
        import noetrium
        from noetrium import api

        self.assertEqual(noetrium.__all__, ["api", "__version__"])
        self.assertEqual(
            api.__all__,
            ("ResearchPortfolioBuilder", "ResearchPortfolio", "ResearchOS", "open_project"),
        )
        for retired in (
            "research_authoring",
            "execution_authoring",
            "research_requirements",
            "research_os",
            "MethodProgramBuilder",
            "MemoryProgramBuilder",
            "Study",
        ):
            self.assertFalse(hasattr(api, retired), retired)

    def test_removed_extension_aliases_are_not_importable(self):
        for module_name in (
            "noetrium" + suffix
            for suffix in (".adapters", ".components", ".orchestration")
        ):
            with self.assertRaises(ModuleNotFoundError):
                importlib.import_module(module_name)


if __name__ == "__main__":
    unittest.main()
