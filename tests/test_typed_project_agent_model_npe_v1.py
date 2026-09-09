from __future__ import annotations

import hashlib

import ast
from dataclasses import dataclass

import pytest

from noetrium_platform.capabilities.model.api import (
    ModelBindingDiagnosticCode,
    ModelCapabilityRequirement,
    ModelProjectBindingError,
    ModelProviderProfile,
    ProjectModelClientPort,
    ProjectModelProviderPort,
    ProjectModelRequest,
)
from noetrium_platform.capabilities.model.providers import QualifiedModelProjectProvider
from noetrium_platform.capabilities.model.request.api import ContentRef, ModelRequestEnvelope
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointRequest,
    ModelEndpointResponse,
    ModelEndpointRoute,
    QualifiedModelEndpointBinding,
)
from noetrium_platform.capabilities.participant.api import (
    AgentIdentity,
    AgentProjectDefinition,
    ParticipantBindingDiagnosticCode,
    ParticipantProjectBindingError,
    ParticipantProviderProfile,
    ParticipantRequirement,
    ProjectParticipantProviderPort,
)
from noetrium_platform.capabilities.participant.core.api.contracts import (
    ParticipantRuntimeBinding,
    ParticipantSessionRuntimeIdentity,
)
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantRuntimeHandle
from noetrium_platform.capabilities.participant.providers import RuntimeParticipantProjectProvider
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity, canonical_digest


D = {
    "prompt": "1" * 64,
    "tool": "2" * 64,
    "generation": "3" * 64,
    "stack": "4" * 64,
    "certificate": "5" * 64,
    "runtime": "6" * 64,
    "host": "7" * 64,
    "canary": "8" * 64,
}


def _model(name: str = "model-a") -> ImmutableModelIdentity:
    return ImmutableModelIdentity(
        logical_name=name,
        model_id=name,
        revision="rev-1",
        engine="engine",
        engine_version="1",
        dtype="bf16",
        quantization=None,
        context_length=8192,
        tokenizer_revision="tok-1",
    )


def _requirement(**changes: object) -> ModelCapabilityRequirement:
    values: dict[str, object] = {
        "role": "planner",
        "prompt_generation_id": "prompt-generation-v1",
        "prompt_id": "planner.v1",
        "prompt_digest": D["prompt"],
        "required_capabilities": ("chat", "tools"),
        "minimum_context_tokens": 4096,
        "tool_schema_sha256": D["tool"],
    }
    values.update(changes)
    return ModelCapabilityRequirement(**values)  # type: ignore[arg-type]


def _qualified_binding(
    *, deployment_id: str = "dep-a", model: ImmutableModelIdentity | None = None,
    prompt_generation: str = "prompt-generation-v1",
) -> QualifiedModelEndpointBinding:
    return QualifiedModelEndpointBinding(
        role="planner",
        deployment_id=deployment_id,
        deployment_generation=D["generation"],
        base_url="http://127.0.0.1:8000",
        model=_model() if model is None else model,
        model_stack_digest=D["stack"],
        qualification_certificate_digest=D["certificate"],
        runtime_qualification_digest=D["runtime"],
        host_identity_digest=D["host"],
        prompt_generation=prompt_generation,
        max_admitted_concurrency=2,
        runtime_canary_evidence_digests=(D["canary"],),
    )


class _BindingPort:
    def __init__(self, binding: QualifiedModelEndpointBinding) -> None:
        self.binding = binding

    def binding_for(self, *, role: str, prompt_generation: str) -> QualifiedModelEndpointBinding:
        return self.binding


@dataclass
class _Endpoint:
    route: ModelEndpointRoute
    calls: list[ModelEndpointRequest]

    def complete(self, request: ModelEndpointRequest) -> ModelEndpointResponse:
        self.calls.append(request)
        return ModelEndpointResponse(
            request_id=request.request.request_id,
            deployment_id=request.deployment_id,
            text="ok",
            finish_reason="stop",
            input_tokens=3,
            output_tokens=1,
        )


def _endpoint_factory(binding: QualifiedModelEndpointBinding) -> _Endpoint:
    return _Endpoint(
        ModelEndpointRoute(
            binding.deployment_id,
            binding.deployment_generation,
            binding.base_url,
            binding.completion_path,
            binding.timeout_s,
        ),
        [],
    )


def _envelope(
    model: ImmutableModelIdentity,
    *, body: object | None = None, prompt_digest: str = D["prompt"],
    prompt_generation: str = "prompt-generation-v1",
    tool_digest: str = D["tool"],
) -> ModelRequestEnvelope:
    visible_body = {"messages": []} if body is None else body
    return ModelRequestEnvelope(
        schema_version="model-request.v1",
        request_id="request-1",
        context=ExecutionContext("run-1", "trace-1", "span-1"),
        role="planner",
        model=model,
        prompt_generation_id=prompt_generation,
        prompt_id="planner.v1",
        prompt_digest=prompt_digest,
        request_body=ContentRef(canonical_digest(visible_body), 2, "application/json"),
        tool_schema_bundle=ContentRef(tool_digest, 2, "application/json"),
    )


class _RequestVerifier:
    def verify_visible_request(self, envelope: ModelRequestEnvelope, actual_body: object) -> None:
        if canonical_digest(actual_body) != envelope.request_body.sha256:
            raise RuntimeError("model-visible request drift")


def _provider(binding: QualifiedModelEndpointBinding) -> QualifiedModelProjectProvider:
    return QualifiedModelProjectProvider(
        ModelProviderProfile("qualified-local", ("chat", "tools")),
        _BindingPort(binding),
        _endpoint_factory,
        _RequestVerifier(),  # type: ignore[arg-type]
    )


def test_common_project_source_uses_only_role04_public_api() -> None:
    source = """
from noetrium_platform.capabilities.model.api import ModelCapabilityRequirement
from noetrium_platform.capabilities.participant.api import (
    AgentIdentity, AgentProjectDefinition, AgentSession, AgentTurnResult,
)

AGENT = AgentProjectDefinition(
    role='worker',
    identity=AgentIdentity('agent', '1', '1', '1', 'a' * 64),
    required_capabilities=('observe',),
)
MODEL = ModelCapabilityRequirement(
    role='planner', prompt_generation_id='gen', prompt_id='prompt',
    prompt_digest='1' * 64, required_capabilities=('chat',),
)
class DemoSession:
    def run_turn(self, request, capabilities): return AgentTurnResult({'ok': True})
    def checkpoint(self): return None
    def restore(self, snapshot): return None
    def diagnostics(self): return {}
    def close(self): return None
DEMO_SESSION = DemoSession()
"""
    tree = ast.parse(source)
    modules = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
    }
    assert modules == {
        "noetrium_platform.capabilities.model.api",
        "noetrium_platform.capabilities.participant.api",
    }
    namespace: dict[str, object] = {}
    exec(compile(tree, "project.py", "exec"), namespace)
    assert isinstance(namespace["AGENT"], AgentProjectDefinition)
    assert isinstance(namespace["MODEL"], ModelCapabilityRequirement)
    assert isinstance(namespace["DEMO_SESSION"], namespace["AgentSession"])


def test_model_provider_conformance_and_binding_hide_route_process_details() -> None:
    requirement = _requirement()
    provider = _provider(_qualified_binding())
    assert isinstance(provider, ProjectModelProviderPort)
    client = provider.bind(requirement)
    assert isinstance(client, ProjectModelClientPort)
    assert client.binding.requirement_digest == requirement.digest()
    assert client.binding.prompt_digest == requirement.prompt_digest
    assert client.binding.runtime_canary_evidence_digests == (D["canary"],)
    assert not hasattr(client.binding, "base_url")
    assert not hasattr(client.binding, "completion_path")
    assert not hasattr(client.binding, "pid")
    assert not hasattr(client.binding, "process_start_marker")


def test_generation_binding_is_materialized_once_per_requirement() -> None:
    requirement = _requirement()
    binding = _qualified_binding()

    class CountingBindingPort(_BindingPort):
        def __init__(self, value):
            super().__init__(value)
            self.calls = 0

        def binding_for(self, *, role: str, prompt_generation: str):
            self.calls += 1
            return super().binding_for(role=role, prompt_generation=prompt_generation)

    bindings = CountingBindingPort(binding)
    endpoint_calls = []

    def factory(value):
        endpoint_calls.append(value)
        return _endpoint_factory(value)

    provider = QualifiedModelProjectProvider(
        ModelProviderProfile("qualified-local", ("chat", "tools")),
        bindings,
        factory,
        _RequestVerifier(),  # type: ignore[arg-type]
    )

    first = provider.bind(requirement)
    second = provider.bind(requirement)

    assert first is second
    assert bindings.calls == 1
    assert len(endpoint_calls) == 1


def test_model_request_binds_exact_prompt_tool_and_deployment_provenance() -> None:
    requirement = _requirement()
    client = _provider(_qualified_binding()).bind(requirement)
    body = {"messages": [{"role": "user", "content": "hello"}]}
    envelope = _envelope(client.binding.model, body=body)
    request = ProjectModelRequest(requirement.digest(), envelope, body)
    body["messages"][0]["content"] = "mutated"
    response = client.complete(request)
    assert response.request_digest == request.request_digest
    assert response.binding_digest == client.binding.digest()
    assert response.text == "ok"
    assert not hasattr(response, "response")
    assert request.body["messages"][0]["content"] == "hello"


@pytest.mark.parametrize(
    ("envelope", "match"),
    [
        (_envelope(_model(), prompt_digest="a" * 64), "prompt provenance"),
        (_envelope(_model(), prompt_generation="other"), "prompt provenance"),
        (_envelope(_model(), tool_digest="b" * 64), "tool schema provenance"),
    ],
)
def test_model_request_provenance_drift_fails_closed(
    envelope: ModelRequestEnvelope, match: str
) -> None:
    requirement = _requirement()
    client = _provider(_qualified_binding()).bind(requirement)
    request = ProjectModelRequest(requirement.digest(), envelope, {"messages": []})
    with pytest.raises(ValueError, match=match):
        client.complete(request)


def test_model_provider_rejects_binding_role_or_prompt_generation_drift() -> None:
    requirement = _requirement()
    drifted = _qualified_binding(prompt_generation="wrong-generation")
    provider = _provider(drifted)
    diagnostics = provider.diagnose(requirement)
    assert diagnostics[0].code is ModelBindingDiagnosticCode.BINDING_PROVENANCE_DRIFT
    with pytest.raises(ModelProjectBindingError):
        provider.bind(requirement)


def test_model_provider_swap_preserves_project_requirement_and_logic() -> None:
    requirement = _requirement()
    first = _provider(_qualified_binding(deployment_id="dep-a", model=_model("model-a"))).bind(requirement)
    second = _provider(_qualified_binding(deployment_id="dep-b", model=_model("model-b"))).bind(requirement)

    def project_logic(client: ProjectModelClientPort) -> str:
        request = ProjectModelRequest(
            requirement.digest(),
            _envelope(client.binding.model, body={"messages": [{"role": "user", "content": "plan"}]}),
            {"messages": [{"role": "user", "content": "plan"}]},
        )
        return client.complete(request).text

    assert project_logic(first) == "ok"
    assert project_logic(second) == "ok"
    assert first.binding.requirement_digest == second.binding.requirement_digest
    assert first.binding.deployment_id != second.binding.deployment_id
    assert first.binding.model != second.binding.model


class _FailingBindingPort:
    def binding_for(self, *, role: str, prompt_generation: str) -> QualifiedModelEndpointBinding:
        raise RuntimeError("https://secret.invalid?token=do-not-leak")


def test_model_doctor_diagnostics_are_typed_and_do_not_echo_provider_secrets() -> None:
    requirement = _requirement()
    provider = QualifiedModelProjectProvider(
        ModelProviderProfile("qualified-local", ("chat", "tools")),
        _FailingBindingPort(),
        _endpoint_factory,
        _RequestVerifier(),  # type: ignore[arg-type]
    )
    diagnostics = provider.diagnose(requirement)
    assert diagnostics[0].code is ModelBindingDiagnosticCode.QUALIFIED_BINDING_UNAVAILABLE
    assert diagnostics[0].requirement_digest == requirement.digest()
    assert "secret.invalid" not in diagnostics[0].message
    assert "token=" not in diagnostics[0].message


def test_model_doctor_reports_capability_and_context_failures_without_endpoint_materialization() -> None:
    missing = QualifiedModelProjectProvider(
        ModelProviderProfile("small", ("chat",)),
        _BindingPort(_qualified_binding()),
        lambda binding: (_ for _ in ()).throw(AssertionError("must not materialize")),
        _RequestVerifier(),  # type: ignore[arg-type]
    )
    assert missing.diagnose(_requirement())[0].code is ModelBindingDiagnosticCode.CAPABILITY_MISSING
    short = _provider(_qualified_binding(model=ImmutableModelIdentity(
        "short", "short", "rev", "engine", "1", "bf16", None, 1024, None
    )))
    assert short.diagnose(_requirement())[0].code is ModelBindingDiagnosticCode.CONTEXT_INSUFFICIENT


def _participant_requirement() -> ParticipantRequirement:
    definition = AgentProjectDefinition(
        role="worker",
        identity=AgentIdentity("agent", "1", "1", "1", "a" * 64),
        configuration_digest="b" * 64,
        required_capabilities=("observe", "act"),
    )
    return definition.requirement()


def _runtime(runtime_id: str = "local-agent-runtime") -> ParticipantSessionRuntimeIdentity:
    return ParticipantSessionRuntimeIdentity(
        runtime_id=runtime_id,
        runtime_version="1",
        abi_version="1",
        artifact_digest=hashlib.sha256(f"artifact-{runtime_id}".encode()).hexdigest(),
    )


class _ParticipantResolver:
    def resolve(self, binding: ParticipantRuntimeBinding) -> ParticipantRuntimeHandle:
        return ParticipantRuntimeHandle(binding, object())  # type: ignore[arg-type]


def _participant_provider(runtime_id: str = "local-agent-runtime") -> RuntimeParticipantProjectProvider:
    return RuntimeParticipantProjectProvider(
        ParticipantProviderProfile("participant-local", ("agent",), ("observe", "act")),
        _ParticipantResolver(),
        lambda requirement: _runtime(runtime_id),
    )


def test_participant_provider_conformance_binds_agent_without_runtime_imports_in_project() -> None:
    requirement = _participant_requirement()
    provider = _participant_provider()
    assert isinstance(provider, ProjectParticipantProviderPort)
    binding = provider.bind(requirement)
    assert binding.requirement_digest == requirement.digest()
    assert binding.binding.role == "worker"
    assert binding.binding.implementation == requirement.implementation
    assert binding.binding.configuration_digest == requirement.configuration_digest


def test_participant_provider_swap_preserves_project_requirement_identity() -> None:
    requirement = _participant_requirement()
    local = _participant_provider("local").bind(requirement)
    server = _participant_provider("server").bind(requirement)
    assert local.requirement_digest == server.requirement_digest == requirement.digest()
    assert local.binding.implementation == server.binding.implementation
    assert local.binding.runtime != server.binding.runtime


def test_participant_doctor_reports_missing_capability_as_typed_failure() -> None:
    provider = RuntimeParticipantProjectProvider(
        ParticipantProviderProfile("participant-small", ("agent",), ("observe",)),
        _ParticipantResolver(),
        lambda requirement: _runtime(),
    )
    diagnostics = provider.diagnose(_participant_requirement())
    assert diagnostics[0].code is ParticipantBindingDiagnosticCode.CAPABILITY_MISSING
    with pytest.raises(ParticipantProjectBindingError):
        provider.bind(_participant_requirement())


class _FailingParticipantResolver:
    def resolve(self, binding: ParticipantRuntimeBinding) -> ParticipantRuntimeHandle:
        raise RuntimeError("C:/secret/provider/path token=do-not-leak")


def test_participant_doctor_does_not_echo_provider_secrets() -> None:
    requirement = _participant_requirement()
    provider = RuntimeParticipantProjectProvider(
        ParticipantProviderProfile("participant-local", ("agent",), ("observe", "act")),
        _FailingParticipantResolver(),
        lambda req: _runtime(),
    )
    diagnostics = provider.diagnose(requirement)
    assert diagnostics[0].code is ParticipantBindingDiagnosticCode.RUNTIME_UNAVAILABLE
    assert diagnostics[0].requirement_digest == requirement.digest()
    assert "secret/provider" not in diagnostics[0].message
    assert "token=" not in diagnostics[0].message


class _DriftingParticipantResolver:
    def resolve(self, binding: ParticipantRuntimeBinding) -> ParticipantRuntimeHandle:
        drifted = ParticipantRuntimeBinding(
            role="other",
            implementation=binding.implementation,
            runtime=binding.runtime,
            configuration_digest=binding.configuration_digest,
        )
        return ParticipantRuntimeHandle(drifted, object())  # type: ignore[arg-type]


def test_participant_provider_detects_resolver_binding_drift() -> None:
    requirement = _participant_requirement()
    provider = RuntimeParticipantProjectProvider(
        ParticipantProviderProfile("participant-local", ("agent",), ("observe", "act")),
        _DriftingParticipantResolver(),
        lambda req: _runtime(),
    )
    diagnostics = provider.diagnose(requirement)
    assert diagnostics[0].code is ParticipantBindingDiagnosticCode.BINDING_PROVENANCE_DRIFT
    with pytest.raises(ParticipantProjectBindingError):
        provider.bind(requirement)


def test_role04_public_exports_are_reflection_safe_strings() -> None:
    import noetrium_platform.capabilities.model.api as model_api
    import noetrium_platform.capabilities.participant.api as participant_api

    assert model_api.__all__
    assert participant_api.__all__
    assert all(type(name) is str for name in model_api.__all__)
    assert all(type(name) is str for name in participant_api.__all__)


def test_provider_ports_fail_closed_on_untyped_requirements() -> None:
    with pytest.raises(TypeError, match="typed"):
        _provider(_qualified_binding()).diagnose(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="typed"):
        _participant_provider().diagnose(object())  # type: ignore[arg-type]


def test_common_public_modules_do_not_export_provider_runtime_constructors() -> None:
    import noetrium_platform.capabilities.model.api as model_api
    import noetrium_platform.capabilities.participant.api as participant_api

    assert not hasattr(model_api, "QualifiedModelProjectProvider")
    assert not hasattr(model_api, "EndpointFactory")
    assert not hasattr(participant_api, "RuntimeParticipantProjectProvider")
    assert not hasattr(participant_api, "RuntimeSelector")
    assert not hasattr(participant_api, "ParticipantSessionRuntimeIdentity")


def test_project_client_does_not_expose_endpoint_authority() -> None:
    client = _provider(_qualified_binding()).bind(_requirement())
    assert not hasattr(client, "endpoint")
    assert not hasattr(client, "route")
    assert not hasattr(client, "base_url")


def test_actual_model_visible_body_drift_fails_closed() -> None:
    requirement = _requirement()
    client = _provider(_qualified_binding()).bind(requirement)
    envelope = _envelope(client.binding.model, body={"messages": []})
    request = ProjectModelRequest(
        requirement.digest(), envelope,
        {"messages": [{"role": "user", "content": "different"}]},
    )
    with pytest.raises(RuntimeError, match="model-visible request drift"):
        client.complete(request)


class _DriftResponseEndpoint(_Endpoint):
    def complete(self, request: ModelEndpointRequest) -> ModelEndpointResponse:
        return ModelEndpointResponse(
            request_id="other-request",
            deployment_id=request.deployment_id,
            text="wrong provenance",
        )


def test_model_response_provenance_drift_fails_closed() -> None:
    requirement = _requirement()
    provider = QualifiedModelProjectProvider(
        ModelProviderProfile("qualified-local", ("chat", "tools")),
        _BindingPort(_qualified_binding()),
        lambda binding: _DriftResponseEndpoint(_endpoint_factory(binding).route, []),
        _RequestVerifier(),  # type: ignore[arg-type]
    )
    client = provider.bind(requirement)
    body = {"messages": []}
    request = ProjectModelRequest(requirement.digest(), _envelope(client.binding.model, body=body), body)
    with pytest.raises(ValueError, match="response provenance drift"):
        client.complete(request)


def _psc_subjects(system_id: str):
    from noetrium_platform.foundation.governance.architecture.api import CompositionSubject
    from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity

    return (
        CompositionSubject.system_subject(SystemIdentity(system_id)),
        CompositionSubject.project_subject("synthetic-paper", "1"),
    )


def test_model_binding_projects_success_into_neutral_psc03_resolution() -> None:
    from noetrium_platform.foundation.governance.architecture.api import BindingResolutionState
    from noetrium_platform.capabilities.model.composition import ModelBindingResolutionAdapter

    requirement = _requirement()
    provider = _provider(_qualified_binding())
    owner, subject = _psc_subjects("model")
    resolution = ModelBindingResolutionAdapter(
        provider, owner=owner, subject=subject, requirement_id="model.primary"
    ).resolve(requirement)

    assert resolution.state is BindingResolutionState.BOUND
    assert resolution.binding is not None
    assert resolution.binding.requirement_digest == requirement.digest()
    assert resolution.proof is not None
    assert resolution.proof.owner == owner
    assert resolution.proof.subject == subject
    assert resolution.proof.provider_identity == provider.profile.provider_id
    assert resolution.proof.provider_profile_digest.value == provider.profile.digest()
    assert resolution.proof.binding_generation.startswith("model-")


def test_model_binding_projects_domain_failure_into_neutral_psc03_diagnostic() -> None:
    from noetrium_platform.foundation.governance.architecture.api import BindingResolutionState
    from noetrium_platform.capabilities.model.composition import ModelBindingResolutionAdapter

    requirement = _requirement()
    provider = QualifiedModelProjectProvider(
        ModelProviderProfile("small", ("chat",)),
        _BindingPort(_qualified_binding()),
        _endpoint_factory,
        _RequestVerifier(),  # type: ignore[arg-type]
    )
    owner, subject = _psc_subjects("model")
    resolution = ModelBindingResolutionAdapter(
        provider, owner=owner, subject=subject, requirement_id="model.primary"
    ).resolve(requirement)

    assert resolution.state is BindingResolutionState.DIAGNOSTIC
    diagnostic = resolution.diagnostics[0]
    assert diagnostic.code.value == "model.capability_missing"
    assert diagnostic.requirement_digest.value == requirement.digest()
    assert diagnostic.provider_profile_digest is not None
    assert diagnostic.provider_profile_digest.value == provider.profile.digest()


def test_participant_binding_projects_success_into_neutral_psc03_resolution() -> None:
    from noetrium_platform.foundation.governance.architecture.api import BindingResolutionState
    from noetrium_platform.capabilities.participant.composition import ParticipantBindingResolutionAdapter

    requirement = _participant_requirement()
    provider = _participant_provider()
    owner, subject = _psc_subjects("participant")
    resolution = ParticipantBindingResolutionAdapter(
        provider, owner=owner, subject=subject, requirement_id="participant.primary"
    ).resolve(requirement)

    assert resolution.state is BindingResolutionState.BOUND
    assert resolution.binding is not None
    assert resolution.binding.requirement_digest == requirement.digest()
    assert resolution.proof is not None
    assert resolution.proof.owner == owner
    assert resolution.proof.subject == subject
    assert resolution.proof.provider_identity == provider.profile.provider_id
    assert resolution.proof.provider_profile_digest.value == provider.profile.digest()
    assert resolution.proof.binding_generation.startswith("participant-")


def test_participant_binding_projects_domain_failure_into_neutral_psc03_diagnostic() -> None:
    from noetrium_platform.foundation.governance.architecture.api import BindingResolutionState
    from noetrium_platform.capabilities.participant.composition import ParticipantBindingResolutionAdapter

    requirement = _participant_requirement()
    provider = RuntimeParticipantProjectProvider(
        ParticipantProviderProfile("participant-small", ("agent",), ("observe",)),
        _ParticipantResolver(),
        lambda req: _runtime(),
    )
    owner, subject = _psc_subjects("participant")
    resolution = ParticipantBindingResolutionAdapter(
        provider, owner=owner, subject=subject, requirement_id="participant.primary"
    ).resolve(requirement)

    assert resolution.state is BindingResolutionState.DIAGNOSTIC
    diagnostic = resolution.diagnostics[0]
    assert diagnostic.code.value == "participant.capability_missing"
    assert diagnostic.requirement_digest.value == requirement.digest()
    assert diagnostic.provider_identity == provider.profile.provider_id
    assert diagnostic.provider_profile_digest is not None
    assert diagnostic.provider_profile_digest.value == provider.profile.digest()
