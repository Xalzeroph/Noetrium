from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace

import pytest

from noetrium_platform.capabilities.model.api import (
    ModelCapabilityInvocation,
    ModelCapabilityRequirement,
    ModelProviderProfile,
    MultimodalPart,
    MultimodalRequest,
    WorldModelActionStep,
    WorldModelActionTrajectory,
    WorldModelInput,
    WorldModelMode,
)
from noetrium_platform.capabilities.model.providers import QualifiedModelProjectProvider
from noetrium_platform.capabilities.model.request.api import ModelOperationEnvelope
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointReplicaSet,
    ModelEndpointResponse,
    QualifiedModelEndpointBinding,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    ImmutableModelIdentity,
    canonical_bytes,
)
from noetrium_platform.substrate.api import ArtifactBlobRef
from tests._model_tokenization_support import FixedModelRequestTokenizationProvider


def _model() -> ImmutableModelIdentity:
    return ImmutableModelIdentity(
        "universal-model",
        "org/universal-model",
        "rev-mm-wm-1",
        "native",
        "1",
        "bf16",
        None,
        32768,
    )


def _context() -> ExecutionContext:
    return ExecutionContext("run-mm-wm", "trace-mm-wm", "span-mm-wm")


def _requirement(capability_id: str, input_schema_id: str, output_schema_id: str):
    return ModelCapabilityRequirement(
        role="scientist",
        required_capabilities=(capability_id,),
        capability_id=capability_id,
        input_schema_id=input_schema_id,
        output_schema_id=output_schema_id,
    )


def _qualified(requirement: ModelCapabilityRequirement) -> QualifiedModelEndpointBinding:
    return QualifiedModelEndpointBinding(
        role=requirement.role,
        capability_id=requirement.capability_id,
        input_schema_id=requirement.input_schema_id,
        output_schema_id=requirement.output_schema_id,
        deployment_id=f"dep-{requirement.capability_id}",
        deployment_generation="1" * 64,
        base_url="http://127.0.0.1:18000",
        model=_model(),
        model_stack_digest="2" * 64,
        qualification_certificate_digest="3" * 64,
        runtime_qualification_digest="4" * 64,
        host_identity_digest="5" * 64,
        prompt_generation=None,
        max_admitted_concurrency=2,
        runtime_canary_evidence_digests=("6" * 64,),
        tokenizer_sha256=None,
        chat_template_sha256=None,
        verified_capabilities=(requirement.capability_id,),
    )


class _Bindings:
    def __init__(self, binding):
        self.binding=binding

    def binding_for(
        self,
        *,
        role,
        capability_id,
        input_schema_id,
        output_schema_id,
        prompt_generation=None,
    ):
        assert (
            role,
            capability_id,
            input_schema_id,
            output_schema_id,
            prompt_generation,
        ) == (
            self.binding.role,
            self.binding.capability_id,
            self.binding.input_schema_id,
            self.binding.output_schema_id,
            None,
        )
        return self.binding

    def replica_set_for(
        self,
        *,
        role,
        capability_id,
        input_schema_id,
        output_schema_id,
        prompt_generation=None,
    ):
        assert (
            role,
            capability_id,
            input_schema_id,
            output_schema_id,
            prompt_generation,
        ) == (
            self.binding.role,
            self.binding.capability_id,
            self.binding.input_schema_id,
            self.binding.output_schema_id,
            None,
        )
        return ModelEndpointReplicaSet((self.binding,))


class _Recorder:
    durability="test"

    def __init__(self):
        self.operation_kwargs=None
        self.envelope=None

    def record(self, **kwargs):
        raise AssertionError("non-generation capability must not use generation recorder")

    def record_operation(self, **kwargs):
        self.operation_kwargs=dict(kwargs)
        raw=canonical_bytes(kwargs["request_body"])
        self.envelope=ModelOperationEnvelope(
            schema_version="model-operation.v1",
            request_id=kwargs["request_id"],
            context=kwargs["context"],
            role=kwargs["role"],
            model=kwargs["model"],
            capability_id=kwargs["capability_id"],
            input_schema_id=kwargs["input_schema_id"],
            output_schema_id=kwargs["output_schema_id"],
            request_body=ArtifactBlobRef(
                sha256(raw).hexdigest(), len(raw), "application/json"
            ),
            source_artifact_refs=kwargs.get("source_artifact_refs", ()),
            source_state_refs=kwargs.get("source_state_refs", ()),
        )
        return self.envelope

    def reconstruct(self, envelope):
        raise AssertionError("not used")

    def reconstruct_request_body(self, envelope):
        raise AssertionError("not used")

    def verify_visible_request(self, envelope, actual_body):
        assert envelope is self.envelope
        assert canonical_bytes(actual_body) == canonical_bytes(
            self.operation_kwargs["request_body"]
        )


class _Pool:
    def __init__(self, binding, payload):
        self.binding=binding
        self.payload=payload
        self.last_envelope=None
        self.last_body=None

    @property
    def replica_set(self):
        return ModelEndpointReplicaSet((self.binding,))

    def snapshot(self):
        return None

    def complete(self, envelope, body):
        self.last_envelope=envelope
        self.last_body=body
        response=ModelEndpointResponse(
            request_id=envelope.request_id,
            deployment_id=self.binding.deployment_id,
            payload=self.payload,
        )
        return SimpleNamespace(
            request=SimpleNamespace(
                deployment_id=self.binding.deployment_id,
                deployment_generation=self.binding.deployment_generation,
            ),
            response=response,
            dispatch_digest="7" * 64,
        )


def _provider(requirement, recorder, pool):
    binding=_qualified(requirement)
    return QualifiedModelProjectProvider(
        ModelProviderProfile("qualified-universal", (requirement.capability_id,)),
        _Bindings(binding),
        lambda replica_set: pool,
        recorder,
        FixedModelRequestTokenizationProvider(),
    )


def test_multimodal_runs_through_qualified_typed_physical_plane_with_artifact_refs():
    requirement=_requirement(
        "multimodal-inference",
        "model.multimodal.request.v1",
        "model.multimodal.response.v1",
    )
    binding=_qualified(requirement)
    image=ArtifactBlobRef("a" * 64, 4096, "image/png")
    derived=ArtifactBlobRef("b" * 64, 1024, "application/json")
    request=MultimodalRequest(
        (
            MultimodalPart(
                "observation",
                image,
                modality_id="image",
                source_refs=("dataset:item-7",),
            ),
        ),
        instruction="inspect",
    )
    response_payload={
        "text":"object detected",
        "parts":(
            {
                "role":"evidence",
                "content":{
                    "content_sha256":derived.content_sha256,
                    "size_bytes":derived.size_bytes,
                    "media_type":derived.media_type,
                },
                "modality_id":"application/json",
                "sequence_index":0,
                "metadata":{"kind":"detector-output"},
                "source_refs":(),
            },
        ),
        "metadata":{"backend":"test"},
    }
    recorder=_Recorder()
    pool=_Pool(binding,response_payload)
    provider=QualifiedModelProjectProvider(
        ModelProviderProfile("qualified-universal", ("multimodal-inference",)),
        _Bindings(binding),
        lambda replica_set: pool,
        recorder,
        FixedModelRequestTokenizationProvider(),
    )
    invocation=ModelCapabilityInvocation.from_requirement(
        requirement,"mm-1",request,context=_context()
    )
    response=provider.bind_capability(requirement).invoke(invocation)

    assert isinstance(pool.last_envelope,ModelOperationEnvelope)
    assert pool.last_envelope.capability_id == "multimodal-inference"
    assert pool.last_envelope.source_artifact_refs == (
        image.content_sha256,
        "dataset:item-7",
    )
    assert pool.last_body["parts"][0]["content"]["content_sha256"] == image.content_sha256
    assert response.output.text == "object detected"
    assert response.output.parts[0].content == derived
    assert response.output.model_revision == _model().revision
    assert response.operational_dispatch_digest == "7" * 64


def test_world_model_runs_same_qualified_plane_and_preserves_mode_and_refs():
    requirement=_requirement(
        "world-model",
        "model.world-model.input.v1",
        "model.world-model.output.v1",
    )
    binding=_qualified(requirement)
    frame=ArtifactBlobRef("c" * 64, 8192, "image/png")
    request=WorldModelInput(
        mode=WorldModelMode.FORWARD_DYNAMICS,
        observations=(MultimodalPart("frame",frame,modality_id="image"),),
        action_trajectory=WorldModelActionTrajectory(
            "robot.action.v1",
            (WorldModelActionStep(0,{"move":"forward"}),),
        ),
        rollout_horizon=4,
        candidates=2,
    )
    response_payload={
        "mode":"forward_dynamics",
        "rollouts":(
            {
                "media":(),
                "predicted_state":{"x":1},
                "score":0.8,
                "terminated":False,
                "metadata":{"candidate":0},
            },
            {
                "media":(),
                "predicted_state":{"x":2},
                "score":0.7,
                "terminated":False,
                "metadata":{"candidate":1},
            },
        ),
        "primary_index":0,
        "metadata":{"horizon":4},
    }
    recorder=_Recorder()
    pool=_Pool(binding,response_payload)
    provider=QualifiedModelProjectProvider(
        ModelProviderProfile("qualified-universal", ("world-model",)),
        _Bindings(binding),
        lambda replica_set: pool,
        recorder,
        FixedModelRequestTokenizationProvider(),
    )
    invocation=ModelCapabilityInvocation.from_requirement(
        requirement,"wm-1",request,context=_context()
    )
    response=provider.bind_capability(requirement).invoke(invocation)

    assert pool.last_envelope.source_artifact_refs == (frame.content_sha256,)
    assert pool.last_body["mode"] == "forward_dynamics"
    assert pool.last_body["action_trajectory"]["steps"][0]["payload"]["move"] == "forward"
    assert response.output.mode is WorldModelMode.FORWARD_DYNAMICS
    assert len(response.output.rollouts) == 2
    assert response.output.primary.predicted_state["x"] == 1
    assert response.operational_deployment_id == binding.deployment_id


def test_world_model_response_mode_drift_fails_closed():
    requirement=_requirement(
        "world-model",
        "model.world-model.input.v1",
        "model.world-model.output.v1",
    )
    binding=_qualified(requirement)
    frame=ArtifactBlobRef("d" * 64, 100, "image/png")
    request=WorldModelInput(
        mode=WorldModelMode.POLICY,
        observations=(MultimodalPart("frame",frame,modality_id="image"),),
        task_prompt="reach target",
    )
    recorder=_Recorder()
    pool=_Pool(
        binding,
        {
            "mode":"inverse_dynamics",
            "rollouts":({"media":(),"predicted_state":{"bad":True}},),
        },
    )
    provider=QualifiedModelProjectProvider(
        ModelProviderProfile("qualified-universal", ("world-model",)),
        _Bindings(binding),
        lambda replica_set: pool,
        recorder,
        FixedModelRequestTokenizationProvider(),
    )
    invocation=ModelCapabilityInvocation.from_requirement(
        requirement,"wm-drift",request,context=_context()
    )
    with pytest.raises(ValueError,match="mode drift"):
        provider.bind_capability(requirement).invoke(invocation)


def test_multimodal_malformed_part_does_not_stringify_invalid_identity():
    requirement=_requirement(
        "multimodal-inference",
        "model.multimodal.request.v1",
        "model.multimodal.response.v1",
    )
    binding=_qualified(requirement)
    image=ArtifactBlobRef("e" * 64, 4, "image/png")
    request=MultimodalRequest(
        (MultimodalPart("observation",image,modality_id="image"),)
    )
    recorder=_Recorder()
    pool=_Pool(
        binding,
        {
            "parts":(
                {
                    "role":None,
                    "content":{
                        "content_sha256":"f" * 64,
                        "size_bytes":1,
                        "media_type":"application/octet-stream",
                    },
                    "modality_id":"binary",
                },
            ),
        },
    )
    provider=QualifiedModelProjectProvider(
        ModelProviderProfile("qualified-universal", ("multimodal-inference",)),
        _Bindings(binding),
        lambda replica_set: pool,
        recorder,
        FixedModelRequestTokenizationProvider(),
    )
    invocation=ModelCapabilityInvocation.from_requirement(
        requirement,"mm-bad",request,context=_context()
    )
    with pytest.raises(ValueError,match="role"):
        provider.bind_capability(requirement).invoke(invocation)

def test_embedding_normalization_is_capability_semantics_not_provider_behavior():
    from noetrium_platform.capabilities.model.api import EmbeddingInput

    requirement=_requirement(
        "embedding",
        "model.embedding.input.v1",
        "model.embedding.output.v1",
    )
    binding=_qualified(requirement)
    recorder=_Recorder()
    pool=_Pool(binding,{"vectors":((3.0,4.0),)})
    provider=QualifiedModelProjectProvider(
        ModelProviderProfile("qualified-universal",("embedding",)),
        _Bindings(binding),
        lambda replica_set:pool,
        recorder,
        FixedModelRequestTokenizationProvider(),
    )
    request=EmbeddingInput(("alpha",),normalize=True)
    invocation=ModelCapabilityInvocation.from_requirement(
        requirement,"embedding-normalize",request,context=_context()
    )
    vector=provider.bind_capability(requirement).invoke(invocation).output.vectors[0]
    assert vector.values == pytest.approx((0.6,0.8))


def test_embedding_response_cardinality_drift_fails_closed():
    from noetrium_platform.capabilities.model.api import EmbeddingInput

    requirement=_requirement(
        "embedding",
        "model.embedding.input.v1",
        "model.embedding.output.v1",
    )
    binding=_qualified(requirement)
    recorder=_Recorder()
    pool=_Pool(binding,{"vectors":((1.0,),(2.0,))})
    provider=QualifiedModelProjectProvider(
        ModelProviderProfile("qualified-universal",("embedding",)),
        _Bindings(binding),
        lambda replica_set:pool,
        recorder,
        FixedModelRequestTokenizationProvider(),
    )
    invocation=ModelCapabilityInvocation.from_requirement(
        requirement,
        "embedding-cardinality",
        EmbeddingInput(("alpha",)),
        context=_context(),
    )
    with pytest.raises(ValueError,match="cardinality drift"):
        provider.bind_capability(requirement).invoke(invocation)
