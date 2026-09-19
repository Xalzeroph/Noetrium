from dataclasses import asdict
from pathlib import Path
import json
import tempfile
import unittest
import zipfile

from noetrium_platform.product.operator.maintenance.api import ControlAction, exact_server_startup_plan
from noetrium_platform.foundation.governance.release.runtime.packager import ReleasePackager
from noetrium_platform.foundation.governance.release.runtime.manifest import build_release_manifest, verify_release_manifest
from tests_support import run_launch_manifest


class ReleaseV15Tests(unittest.TestCase):
    def test_manifest_detects_any_source_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"a.py").write_text("x=1\n"); (root/"docs").mkdir(); (root/"docs"/"x.md").write_text("x")
            m=build_release_manifest(root); self.assertEqual(verify_release_manifest(root,m),())
            (root/"a.py").write_text("x=2\n"); self.assertTrue(verify_release_manifest(root,m))

    def test_deterministic_packager_produces_same_zip(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"src"; root.mkdir(); (root/"a.txt").write_text("a"); (root/"b.txt").write_text("b")
            p=ReleasePackager(); a=p.build(root,Path(td)/"a.zip"); b=p.build(root,Path(td)/"b.zip")
            self.assertEqual(a.sha256,b.sha256); self.assertEqual(a.manifest_digest,b.manifest_digest)
            with zipfile.ZipFile(a.zip_path) as z: self.assertIn("RELEASE_MANIFEST.json",z.namelist())

    def test_launch_manifest_changes_on_any_frozen_identity(self):
        a=run_launch_manifest(release_digest="r", prompt_generation_digest="p", role_model_manifest_digest="m", experiment_spec_digest="s", host_fingerprint="h", command_argv=("python","run"), config_digests=(("c","d"),), seed_identity="seed")
        b=run_launch_manifest(release_digest="r", prompt_generation_digest="other", role_model_manifest_digest="m", experiment_spec_digest="s", host_fingerprint="h", command_argv=("python","run"), config_digests=(("c","d"),), seed_identity="seed")
        self.assertNotEqual(a.digest(),b.digest())

    def test_startup_plan_verifies_before_mutation(self):
        plan=exact_server_startup_plan().steps; first_mutating=next(i for i,x in enumerate(plan) if x.mutating)
        self.assertTrue(all(not x.mutating for x in plan[:first_mutating])); self.assertEqual(plan[first_mutating].action,ControlAction.START_MODEL_SERVICES)
        self.assertEqual(plan[-2].action,ControlAction.START_STUDY)

if __name__=='__main__': unittest.main()
