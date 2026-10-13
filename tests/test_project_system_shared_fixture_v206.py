from __future__ import annotations

import inspect

from tests_support import context_action_spec, frozen_runtime_manifest


def test_frozen_runtime_manifest_exposes_project_manifest_identity() -> None:
    signature = inspect.signature(frozen_runtime_manifest)
    parameter = signature.parameters["project_manifest_digest"]
    assert parameter.default == "f" * 64
    source = inspect.getsource(frozen_runtime_manifest)
    assert "project_manifest_digest=project_manifest_digest" in source


def test_context_action_fixture_respects_domain_absent_artifact_identity() -> None:
    spec = context_action_spec()
    method, environment = spec.participants
    assert method.implementation.artifact_digest is None
    assert environment.implementation.artifact_digest is None
