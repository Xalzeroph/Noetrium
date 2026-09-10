from __future__ import annotations

from pathlib import Path

from noetrium.platform import (
    QualifiedProjectModelBinding,
    bind_qualified_project_model,
)
from noetrium_platform.capabilities.model.api import (
    ModelCapabilityRequirement,
    ModelProviderProfile,
    ProjectModelProviderPort,
)
from noetrium_platform.capabilities.model.providers.project import QualifiedModelProjectProvider


class _FakeProjectModelProvider:
    def __init__(self, profile: ModelProviderProfile) -> None:
        self.profile = profile
        self.bound: list[ModelCapabilityRequirement] = []
        self.diagnosed: list[ModelCapabilityRequirement] = []

    def bind(self, requirement: ModelCapabilityRequirement):
        self.bound.append(requirement)
        return ("client", requirement)

    def diagnose(self, requirement: ModelCapabilityRequirement):
        self.diagnosed.append(requirement)
        return ()


def test_qualified_project_model_binding_satisfies_public_provider_protocol() -> None:
    profile = ModelProviderProfile("sem-qualified", ("generation",))
    requirement = ModelCapabilityRequirement(
        role="planner",
        prompt_generation_id="sem-planner",
        prompt_id="minecraft-task-planner",
        prompt_digest="0" * 64,
    )
    binding = object.__new__(QualifiedProjectModelBinding)
    binding._profile = profile
    binding._provider = _FakeProjectModelProvider(profile)
    binding._model_requests = object()
    binding._closed = False
    assert isinstance(binding, ProjectModelProviderPort)
    assert binding.bind(requirement) == ("client", requirement)
    assert binding.diagnose(requirement) == ()
    assert binding.provider.bound == [requirement]
    assert binding.provider.diagnosed == [requirement]


def test_qualified_project_model_binding_rejects_invalid_timeout_before_composition(tmp_path: Path) -> None:
    profile = ModelProviderProfile("sem-qualified", ("generation",))
    try:
        bind_qualified_project_model(
            profile,
            closure_path=tmp_path / "closure.json",
            request_root=tmp_path / "requests",
            timeout_s=0,
        )
    except ValueError as exc:
        assert "timeout_s" in str(exc)
    else:
        raise AssertionError("non-positive model timeout was accepted")


def test_qualified_provider_preserves_binding_failure_detail() -> None:
    class _FailingBindings:
        def binding_for(self, *, role: str, prompt_generation: str):
            raise ValueError(
                "qualification context_length 32768 does not match live endpoint max_model_len 40960"
            )

    profile = ModelProviderProfile("sem-qualified", ("generation",))
    requirement = ModelCapabilityRequirement(
        role="planner",
        prompt_generation_id="sem-planner",
        prompt_id="minecraft-task-planner",
        prompt_digest="0" * 64,
    )
    provider = QualifiedModelProjectProvider(
        profile,
        _FailingBindings(),
        lambda binding: None,
        object(),
    )
    diagnostics = provider.diagnose(requirement)
    assert len(diagnostics) == 1
    assert "max_model_len 40960" in diagnostics[0].message

