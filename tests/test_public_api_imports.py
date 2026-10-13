import importlib
import unittest


class PublicAPIImportTests(unittest.TestCase):
    def test_core_internal_packages_import(self):
        import noetrium_platform.evidence.observability.telemetry as telemetry
        import noetrium_platform.infrastructure.reliability.forensics as forensics
        import noetrium_platform.capabilities.model.serving as model_serving
        import noetrium_platform.product.operator as operator
        import noetrium_platform.capabilities.model.request.prompt.runtime as prompt_runtime

        for module in (telemetry, forensics, model_serving, operator, prompt_runtime):
            self.assertIsNotNone(module)

    def test_public_api_is_exactly_unit_and_run(self):
        import noetrium

        self.assertEqual(noetrium.__all__, ("NoetriumUnit", "run"))

    def test_all_retired_public_roots_are_not_importable(self):
        for module_name in (
            "noetrium.adapters",
            "noetrium.components",
            "noetrium.orchestration",
            "noetrium_platform.product.api",
            "components.api",
            "orchestration.api",
        ):
            with self.assertRaises(ModuleNotFoundError, msg=module_name):
                importlib.import_module(module_name)

    def test_retired_public_symbols_are_absent(self):
        import noetrium

        for retired in (
            "research_authoring",
            "execution_authoring",
            "research_requirements",
            "research_os",
            "ResearchGraphBuilder",
            "MethodProgramBuilder",
            "MethodGraphBuilder",
            "MemoryProgramBuilder",
            "Study",
        ):
            self.assertFalse(hasattr(noetrium, retired), retired)


if __name__ == "__main__":
    unittest.main()
