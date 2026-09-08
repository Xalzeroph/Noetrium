from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from noetrium.platform import QualifiedProjectModelBinding, bind_qualified_project_model
from noetrium_platform.capabilities.model.api import (
    ModelCapabilityRequirement,
    ModelProviderProfile,
    ProjectModelProviderPort,
)


class _Concurrency:
    def __init__(self) -> None:
        self.group = object()
        self.group_ids: list[str] = []
        self.closed = False

    def open_task_group(self, group_id: str):
        self.group_ids.append(group_id)
        return self.group

    def close(self) -> None:
        self.closed = True


class _Admission:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Provider:
    def __init__(self, profile, bindings, endpoint_factory, model_requests) -> None:
        self.profile = profile
        self.bindings = bindings
        self.endpoint_factory = endpoint_factory
        self.model_requests = model_requests
        self.requirements = []
        self.diagnostics = []

    def bind(self, requirement):
        self.requirements.append(requirement)
        return ("client", requirement)

    def diagnose(self, requirement):
        self.diagnostics.append(requirement)
        return ()


class PublicProjectModelBindingTests(TestCase):
    def test_public_binding_owns_runtime_and_satisfies_project_provider_port(self) -> None:
        profile = ModelProviderProfile("sem-qualified", ("generation",))
        requirement = ModelCapabilityRequirement(
            role="planner",
            prompt_generation_id="sem-v1",
            prompt_id="sem-planner",
            prompt_digest="a" * 64,
            required_capabilities=("generation",),
            minimum_context_tokens=1024,
        )
        concurrency = _Concurrency()
        admission = _Admission()
        recorder = object()
        closure = object()
        qualified_bindings = object()

        with TemporaryDirectory() as root, patch(
            "noetrium.platform.build_concurrency_runtime", return_value=concurrency
        ), patch(
            "noetrium.platform.ModelAdmissionRegistry", return_value=admission
        ), patch(
            "noetrium.platform.load_qualified_model_deployment_closure",
            return_value=closure,
        ) as load_closure, patch(
            "noetrium.platform.PersistedQualifiedModelEndpointBinding",
            return_value=qualified_bindings,
        ), patch(
            "noetrium.platform.build_directory_model_request_recorder",
            return_value=recorder,
        ) as build_recorder, patch(
            "noetrium.platform.QualifiedModelProjectProvider", _Provider
        ):
            binding = bind_qualified_project_model(
                profile,
                closure_path=Path(root) / "qualified-model-closure.json",
                request_root=Path(root) / "requests",
                task_group_id="project:model:test",
            )
            self.assertIsInstance(binding, QualifiedProjectModelBinding)
            self.assertIsInstance(binding, ProjectModelProviderPort)
            self.assertIs(binding.profile, profile)
            self.assertIs(binding.model_requests, recorder)
            self.assertEqual(binding.bind(requirement), ("client", requirement))
            self.assertEqual(binding.diagnose(requirement), ())
            self.assertEqual(binding.provider.requirements, [requirement])
            self.assertEqual(binding.provider.diagnostics, [requirement])
            self.assertEqual(concurrency.group_ids, ["project:model:test"])
            self.assertIs(binding.provider.bindings, qualified_bindings)
            load_closure.assert_called_once()
            build_recorder.assert_called_once_with((Path(root) / "requests").resolve())

            binding.close()
            self.assertTrue(admission.closed)
            self.assertTrue(concurrency.closed)
            with self.assertRaisesRegex(RuntimeError, "closed"):
                binding.bind(requirement)
            with self.assertRaisesRegex(RuntimeError, "closed"):
                binding.diagnose(requirement)

    def test_invalid_timeout_fails_before_runtime_construction(self) -> None:
        profile = ModelProviderProfile("sem-qualified", ("generation",))
        with patch("noetrium.platform.build_concurrency_runtime") as build_runtime:
            with self.assertRaisesRegex(ValueError, "timeout_s"):
                bind_qualified_project_model(
                    profile,
                    closure_path="closure.json",
                    request_root="requests",
                    timeout_s=0,
                )
        build_runtime.assert_not_called()
