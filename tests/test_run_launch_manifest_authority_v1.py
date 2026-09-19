from __future__ import annotations

from dataclasses import replace
import unittest

import pytest

from noetrium_platform.research.experimentation.run.manifest.api import CompositionPlanReference
from noetrium_platform.infrastructure.lifecycle.launch_control import RunLaunchIdentity
from tests_support import frozen_runtime_manifest


class RunLaunchManifestAuthorityV1Tests(unittest.TestCase):
    def test_only_the_run_manifest_system_owns_launch_identity(self):
        from noetrium_platform.research.execution.runtime import manager
        from noetrium_platform.foundation.governance.release import api as release_api

        self.assertFalse(hasattr(manager, "FrozenRuntimeManifest"))
        self.assertFalse(hasattr(release_api, "RunLaunchManifest"))

    def test_composition_plan_is_required_and_changes_run_process_generation(self):
        manifest = frozen_runtime_manifest()
        with self.assertRaisesRegex(ValueError, "requires at least one composition plan"):
            replace(manifest, composition_plans=())

        changed = replace(
            manifest,
            composition_plans=(
                CompositionPlanReference(
                    "tests.runtime.composition.v1",
                    "system:tests-runtime",
                    "platform:platform",
                    "b" * 64,
                ),
            ),
        )
        self.assertNotEqual(manifest.digest(), changed.digest())
        self.assertNotEqual(
            RunLaunchIdentity.from_manifest(manifest),
            RunLaunchIdentity.from_manifest(changed),
        )
        self.assertEqual(RunLaunchIdentity.from_manifest(manifest).digest(), manifest.digest())


if __name__ == "__main__":
    unittest.main()


def test_run_launch_manifest_rejects_non_string_identity_values() -> None:
    manifest = frozen_runtime_manifest()
    with pytest.raises(ValueError):
        replace(manifest, release_digest=7)
    with pytest.raises(ValueError):
        replace(manifest, command_argv=("run", False))
    with pytest.raises(ValueError):
        replace(manifest, qualified_deployment_digests=(False,))
    with pytest.raises(ValueError):
        replace(manifest, config_digests=(("config", False),))


def test_project_manifest_digest_is_canonical_and_changes_run_identity() -> None:
    manifest = frozen_runtime_manifest(project_manifest_digest="a" * 64)
    changed = replace(manifest, project_manifest_digest="b" * 64)
    assert manifest.digest() != changed.digest()
    assert RunLaunchIdentity.from_manifest(manifest) != RunLaunchIdentity.from_manifest(changed)
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        replace(manifest, project_manifest_digest="A" * 64)


def test_composition_plan_reference_rejects_non_string_fields() -> None:
    with pytest.raises(ValueError):
        CompositionPlanReference(
            "tests.runtime.composition.v1",
            False,
            "platform:platform",
            "a" * 64,
        )
