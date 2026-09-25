from __future__ import annotations

from prompt_os_test_support import make_prompt_registry
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from noetrium_platform.capabilities.model.request.prompt.runtime import (
    DurablePromptRegistry,
    PromptPublicationError,
    default_block_policies,
    default_output_schemas,
    default_prompt_specs,
)
import noetrium_platform.capabilities.model.request.prompt.runtime.generation_staging as staging_module


class PromptGenerationRecoveryV73Tests(unittest.TestCase):
    def _args(self):
        return default_prompt_specs(), default_block_policies(), default_output_schemas()

    def test_crash_after_staged_file_before_directory_publish_resumes_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = make_prompt_registry(root)
            specs, policies, schemas = self._args()

            original = staging_module.publish_atomic_directory
            with mock.patch.object(
                staging_module,
                "publish_atomic_directory",
                side_effect=OSError("power loss before directory rename"),
            ):
                with self.assertRaises(OSError):
                    reg.stage("g1", specs, policies, schemas)

            tmp = root / "generations" / "g1.tmp" / "generation.json"
            self.assertTrue(tmp.is_file())
            self.assertFalse((root / "generations" / "g1").exists())

            with mock.patch.object(staging_module, "publish_atomic_directory", wraps=original) as publish:
                manifest = reg.stage("g1", specs, policies, schemas)
                self.assertEqual(publish.call_count, 1)

            self.assertTrue((root / "generations" / "g1" / "generation.json").is_file())
            self.assertFalse((root / "generations" / "g1.tmp").exists())
            loaded, _ = reg.generation_store.load("g1")
            self.assertEqual(loaded, manifest)

    def test_retry_after_success_is_idempotent_only_for_exact_payload(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = make_prompt_registry(root)
            specs, policies, schemas = self._args()
            first = reg.stage("g1", specs, policies, schemas)
            second = reg.stage("g1", specs, policies, schemas)
            self.assertEqual(first, second)

            changed = list(specs)
            changed[0] = replace(changed[0], version=changed[0].version + ".changed")
            with self.assertRaises(PromptPublicationError):
                reg.stage("g1", tuple(changed), policies, schemas)

    def test_staged_payload_mismatch_fails_closed_without_deleting_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = make_prompt_registry(root)
            specs, policies, schemas = self._args()

            with mock.patch.object(
                staging_module,
                "publish_atomic_directory",
                side_effect=OSError("cut"),
            ):
                with self.assertRaises(OSError):
                    reg.stage("g1", specs, policies, schemas)

            staged = root / "generations" / "g1.tmp" / "generation.json"
            before = staged.read_bytes()
            changed = list(specs)
            changed[0] = replace(changed[0], version=changed[0].version + ".changed")
            with self.assertRaises(PromptPublicationError):
                reg.stage("g1", tuple(changed), policies, schemas)
            self.assertEqual(staged.read_bytes(), before)
            self.assertFalse((root / "generations" / "g1").exists())


if __name__ == "__main__":
    unittest.main()
