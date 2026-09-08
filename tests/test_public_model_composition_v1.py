from __future__ import annotations

from noetrium.platform import complete_project_model, invoke_multimodal_model
from noetrium_platform.capabilities.model.api import (
    ModelProviderProfile,
    MultimodalPart,
    MultimodalRequest,
    ProjectModelBinding,
    ProjectModelClientPort,
    ProjectModelResponse,
    MultimodalRequestCodecPort,
)
from noetrium_platform.capabilities.model.request.api import (
    ContentAddressedStorePort,
    ContentRef,
)
from noetrium_platform.capabilities.model.request.composition.recorder import (
    build_directory_model_request_recorder,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    ImmutableModelIdentity,
)


def _binding() -> ProjectModelBinding:
    profile = ModelProviderProfile("test-model", ("generation",))
    model = ImmutableModelIdentity(
        "test-model",
        "test/model",
        "rev-1",
        "test-engine",
        "1",
        "bf16",
        None,
        8192,
    )
    return ProjectModelBinding(
        requirement_digest="1" * 64,
        provider_id=profile.provider_id,
        provider_profile_digest=profile.digest(),
        role="agent",
        model=model,
        deployment_id="deployment-1",
        deployment_generation="2" * 64,
        model_stack_digest="3" * 64,
        qualification_certificate_digest="4" * 64,
        runtime_qualification_digest="5" * 64,
        host_identity_digest="6" * 64,
        prompt_generation_id="generation-1",
        prompt_id="agent-prompt",
        prompt_digest="7" * 64,
        capabilities=profile.capabilities,
        runtime_canary_evidence_digests=("8" * 64,),
    )


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        trace_id="trace-1",
        span_id="span-1",
        study_id="study-1",
        task_id="task-1",
        decision_cycle_id="cycle-1",
        participant_generations=(),
    )


class _Client:
    def __init__(self, binding: ProjectModelBinding) -> None:
        self._binding = binding
        self.requests = []

    @property
    def binding(self) -> ProjectModelBinding:
        return self._binding

    def complete(self, request) -> ProjectModelResponse:
        self.requests.append(request)
        return ProjectModelResponse(
            request.request_digest,
            self._binding.digest(),
            "9" * 64,
            "ok",
        )


class _ContentStore:
    durability = "test"

    def put(self, payload: bytes, *, media_type: str) -> ContentRef:
        del payload
        return ContentRef("a" * 64, 0, media_type)

    def get(self, ref: ContentRef) -> bytes:
        del ref
        return b""


class _Codec:
    def encode(self, request, content_store):
        assert content_store is not None
        return {"part_count": len(request.parts), "instruction": request.instruction or ""}


def test_complete_project_model_centralizes_request_provenance(tmp_path) -> None:
    binding = _binding()
    client = _Client(binding)
    recorder = build_directory_model_request_recorder(tmp_path / "requests")
    response = complete_project_model(
        client,
        recorder,
        request_id="request-1",
        context=_context(),
        request_body={"messages": [{"role": "user", "content": "hello"}]},
        compiled_prompt_text="hello",
    )
    assert isinstance(client, ProjectModelClientPort)
    assert response.text == "ok"
    assert client.requests[0].envelope.role == "agent"
    assert recorder.reconstruct_request_body(client.requests[0].envelope)["messages"][0]["content"] == "hello"


def test_invoke_multimodal_model_keeps_codec_and_content_store_provider_owned(tmp_path) -> None:
    binding = _binding()
    client = _Client(binding)
    recorder = build_directory_model_request_recorder(tmp_path / "requests")
    request = MultimodalRequest(
        parts=(
            MultimodalPart(
                "state",
                ContentRef("a" * 64, 3, "application/octet-stream"),
                modality_id="paper/latent-state",
            ),
        ),
        instruction="plan",
    )
    codec = _Codec()
    assert isinstance(codec, MultimodalRequestCodecPort)
    assert isinstance(_ContentStore(), ContentAddressedStorePort)
    response = invoke_multimodal_model(
        client,
        recorder,
        codec,
        _ContentStore(),
        request_id="request-mm-1",
        context=_context(),
        request=request,
    )
    assert response.text == "ok"
    assert client.requests[0].body["part_count"] == 1
    assert "a" * 64 in client.requests[0].envelope.source_artifact_refs
