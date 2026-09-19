from pathlib import Path
import json
import tempfile
import unittest

from noetrium_platform.capabilities.model.request.prompt.runtime import PromptRegistry, default_prompt_specs
from noetrium_platform.foundation.governance.quality.no_degradation import scan_no_degradation


class PromptV6Tests(unittest.TestCase):
    def setUp(self):
        self.registry=PromptRegistry()
        self.registry.publish("g", default_prompt_specs())

    def test_planner_freezes_evidence_and_completion_authority(self):
        text=self.registry.get("planner.v6").text
        self.assertIn("Verified current state", text)
        self.assertIn("historical evidence", text)
        self.assertIn("smallest progress-preserving action", text)
        self.assertIn("verifier evidence", text)
        self.assertIn("Do not reveal hidden chain-of-thought", text)

    def test_semantic_is_grounded_and_preserves_conflicts(self):
        text=self.registry.get("semantic.v6").text
        self.assertIn("J_mem evidence IDs", text)
        self.assertIn("Never use verifier-private", text)
        self.assertIn("retain the disagreement", text)
        self.assertIn("mechanically traceable", text)

    def test_meta_has_structural_only_authority(self):
        text=self.registry.get("meta.v6").text
        self.assertIn("NO_EDIT, CREATE, RETIRE, SPLIT, MERGE", text)
        self.assertIn("runtime resource", text)
        self.assertIn("single failure", text)
        self.assertIn("cannot activate", text.lower())

    def test_diagnostic_distinguishes_unknown_effect(self):
        text=self.registry.get("diagnostic.v3").text
        self.assertIn("Temporal proximity alone is never causality", text)
        self.assertIn("EFFECT_UNKNOWN", text)
        self.assertIn("reconcile/observe", text)
        self.assertIn("Never switch model", text)


class ConfigNoDegradationTests(unittest.TestCase):
    def _scan(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name, payload in files.items():
                path=root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(payload, bytes): path.write_bytes(payload)
                else: path.write_text(payload, encoding="utf-8")
            return scan_no_degradation(root)

    def test_yaml_enabled_downgrade_is_detected(self):
        findings=self._scan({"x.yaml":"runtime:\n  allow_context_downgrade: true\n"})
        self.assertEqual(len(findings),1)
        self.assertEqual(findings[0].kind,"config_enabled")

    def test_yaml_explicit_false_is_allowed(self):
        findings=self._scan({"x.yaml":"runtime:\n  allow_model_fallback: false\n  allow_precision_downgrade: false\n"})
        self.assertEqual(findings,())

    def test_json_fallback_target_is_detected(self):
        findings=self._scan({"x.json":json.dumps({"runtime":{"fallback_models":["small-model"]}})})
        self.assertEqual(len(findings),1)
        self.assertEqual(findings[0].kind,"config_fallback_target")

    def test_toml_enabled_downgrade_is_detected(self):
        findings=self._scan({"x.toml":"[runtime]\nallow_prompt_truncation = true\n"})
        self.assertEqual(len(findings),1)
        self.assertEqual(findings[0].kind,"config_enabled")
