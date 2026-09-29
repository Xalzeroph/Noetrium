from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Generic, TypeVar

from noetrium_platform.capabilities.model.api import (
    EmbeddingInput,
    EmbeddingOutput,
    EmbeddingVector,
    ModelCapabilityInput,
    ModelCapabilityInvocation,
    ModelCapabilityOutput,
    ModelCapabilityRequirement,
    ModelCapabilityResponse,
    ProjectModelCapabilityClientPort,
    MultimodalMethodSpec,
    MultimodalRequest,
    MultimodalResponse,
    PolicyActionProbability,
    PolicyInferenceInput,
    PolicyInferenceOutput,
    RankedCandidate,
    RankingInput,
    RankingOutput,
    ScoredCandidate,
    ScoringInput,
    ScoringOutput,
    ValueInferenceInput,
    ValueInferenceOutput,
    WorldModelActionStep,
    WorldModelActionTrajectory,
    WorldModelInput,
    WorldModelMode,
    WorldModelOutput,
    WorldModelRollout,
)
from noetrium_platform.capabilities.model.api.project import (
    ModelProviderProfile,
    ProjectModelBinding,
)
from noetrium_platform.capabilities.model.request.api import ModelRequestRecorderPort
from noetrium_platform.capabilities.model.serving.api import AdaptiveModelEndpointPoolPort
from noetrium_platform.foundation.kernel.kernel import JsonInput, thaw_json
from noetrium_platform.substrate.api import ArtifactBlobRef, MultimodalPart

from .binding import (
    ReplicaPoolFactory,
    materialize_qualified_replica_pool,
    project_binding_from_qualified,
    resolve_qualified_model_requirement,
)
from noetrium_platform.foundation.kernel.concurrency.api import SingleFlightCache

InputT=TypeVar("InputT",bound=ModelCapabilityInput)
OutputT=TypeVar("OutputT",bound=ModelCapabilityOutput)


class QualifiedCapabilityCodec:
    capability_id: str
    input_schema_id: str
    output_schema_id: str

    def encode(self, payload: ModelCapabilityInput) -> dict[str, JsonInput]:
        raise NotImplementedError

    def decode(
        self,
        payload: object,
        *,
        binding: ProjectModelBinding,
        request: ModelCapabilityInput,
    ) -> ModelCapabilityOutput:
        raise NotImplementedError

    def source_artifact_refs(
        self, payload: ModelCapabilityInput
    ) -> tuple[str, ...]:
        return ()


class _EmbeddingCodec(QualifiedCapabilityCodec):
    capability_id="embedding"
    input_schema_id="model.embedding.input.v1"
    output_schema_id="model.embedding.output.v1"

    def encode(self,payload):
        if not isinstance(payload,EmbeddingInput):
            raise TypeError("embedding capability requires EmbeddingInput")
        return {"texts":payload.texts,"normalize":payload.normalize}

    def decode(self,payload,*,binding,request):
        if not isinstance(request,EmbeddingInput):
            raise TypeError("embedding decode requires EmbeddingInput")
        value=thaw_json(payload)
        if not isinstance(value,dict) or not isinstance(value.get("vectors"),(list,tuple)):
            raise TypeError("embedding endpoint payload is invalid")
        if len(value["vectors"]) != len(request.texts):
            raise ValueError("embedding response cardinality drift")
        vectors=[]
        for row in value["vectors"]:
            vector=EmbeddingVector(tuple(float(x) for x in row))
            if request.normalize:
                norm=math.sqrt(sum(value * value for value in vector.values))
                if not math.isfinite(norm) or norm <= 0.0:
                    raise ValueError("embedding normalization requires non-zero finite vector")
                vector=EmbeddingVector(tuple(value / norm for value in vector.values))
            vectors.append(vector)
        return EmbeddingOutput(
            tuple(vectors),
            model_revision=binding.model.revision,
        )


class _ScoringCodec(QualifiedCapabilityCodec):
    capability_id="scoring"
    input_schema_id="model.scoring.input.v1"
    output_schema_id="model.scoring.output.v1"

    def encode(self,payload):
        if not isinstance(payload,ScoringInput):
            raise TypeError("scoring capability requires ScoringInput")
        return {
            "query":payload.query,
            "candidates":tuple(
                {"candidate_id":row.candidate_id,"text":row.text}
                for row in payload.candidates
            ),
        }

    def decode(self,payload,*,binding,request):
        if not isinstance(request,ScoringInput):
            raise TypeError("scoring decode requires ScoringInput")
        value=thaw_json(payload)
        if not isinstance(value,dict) or not isinstance(value.get("results"),(list,tuple)):
            raise TypeError("scoring endpoint payload is invalid")
        scores=tuple(
            ScoredCandidate(row["candidate_id"],float(row["score"]))
            for row in value["results"]
        )
        expected={row.candidate_id for row in request.candidates}
        actual={row.candidate_id for row in scores}
        if actual != expected:
            raise ValueError("scoring response candidate set drift")
        return ScoringOutput(scores,model_revision=binding.model.revision)


class _RankingCodec(QualifiedCapabilityCodec):
    capability_id="ranking"
    input_schema_id="model.ranking.input.v1"
    output_schema_id="model.ranking.output.v1"

    def encode(self,payload):
        if not isinstance(payload,RankingInput):
            raise TypeError("ranking capability requires RankingInput")
        body={
            "query":payload.query,
            "candidates":tuple(
                {"candidate_id":row.candidate_id,"text":row.text}
                for row in payload.candidates
            ),
        }
        if payload.top_k is not None:
            body["top_k"]=payload.top_k
        return body

    def decode(self,payload,*,binding,request):
        if not isinstance(request,RankingInput):
            raise TypeError("ranking decode requires RankingInput")
        value=thaw_json(payload)
        if not isinstance(value,dict) or not isinstance(value.get("results"),(list,tuple)):
            raise TypeError("ranking endpoint payload is invalid")
        ranking=tuple(
            RankedCandidate(
                row["candidate_id"],index+1,float(row["score"])
            )
            for index,row in enumerate(value["results"])
        )
        expected_count=request.top_k or len(request.candidates)
        if len(ranking) != expected_count:
            raise ValueError("ranking response cardinality drift")
        allowed={row.candidate_id for row in request.candidates}
        if any(row.candidate_id not in allowed for row in ranking):
            raise ValueError("ranking response contains unknown candidate")
        return RankingOutput(ranking,model_revision=binding.model.revision)


class _ValueCodec(QualifiedCapabilityCodec):
    capability_id="value-inference"
    input_schema_id="model.value.input.v1"
    output_schema_id="model.value.output.v1"

    def encode(self,payload):
        if not isinstance(payload,ValueInferenceInput):
            raise TypeError("value capability requires ValueInferenceInput")
        return {
            "features":tuple({"name":x.name,"value":x.value} for x in payload.features),
            "state_id":payload.state_id,
        }

    def decode(self,payload,*,binding,request):
        value=thaw_json(payload)
        if not isinstance(value,dict) or "value" not in value:
            raise TypeError("value endpoint payload is invalid")
        return ValueInferenceOutput(
            float(value["value"]),
            model_revision=binding.model.revision,
            uncertainty=None if value.get("uncertainty") is None else float(value["uncertainty"]),
        )


class _PolicyCodec(QualifiedCapabilityCodec):
    capability_id="policy-inference"
    input_schema_id="model.policy.input.v1"
    output_schema_id="model.policy.output.v1"

    def encode(self,payload):
        if not isinstance(payload,PolicyInferenceInput):
            raise TypeError("policy capability requires PolicyInferenceInput")
        return {
            "state_features":tuple(
                {"name":x.name,"value":x.value} for x in payload.state_features
            ),
            "action_ids":payload.action_ids,
        }

    def decode(self,payload,*,binding,request):
        if not isinstance(request,PolicyInferenceInput):
            raise TypeError("policy decode requires PolicyInferenceInput")
        value=thaw_json(payload)
        if not isinstance(value,dict) or not isinstance(value.get("probabilities"),(list,tuple)):
            raise TypeError("policy endpoint payload is invalid")
        probabilities=tuple(
            PolicyActionProbability(row["action_id"],float(row["probability"]))
            for row in value["probabilities"]
        )
        if {row.action_id for row in probabilities} != set(request.action_ids):
            raise ValueError("policy response action set drift")
        return PolicyInferenceOutput(
            probabilities,
            model_revision=binding.model.revision,
            selected_action_id=value.get("selected_action_id"),
        )



def _part_payload(part: MultimodalPart) -> dict[str, JsonInput]:
    return {
        "role":part.role,
        "content":{
            "content_sha256":part.content.content_sha256,
            "size_bytes":part.content.size_bytes,
            "media_type":part.content.media_type,
        },
        "modality_id":part.modality_id,
        "encoding":part.encoding,
        "part_id":part.part_id,
        "sequence_index":part.sequence_index,
        "timestamp_ns":part.timestamp_ns,
        "duration_ns":part.duration_ns,
        "coordinate_frame":part.coordinate_frame,
        "metadata":part.metadata,
        "source_refs":part.source_refs,
    }


def _part_from_payload(value: object) -> MultimodalPart:
    if not isinstance(value,dict):
        raise TypeError("multimodal part payload must be an object")
    content=value.get("content")
    if not isinstance(content,dict):
        raise TypeError("multimodal part content reference is required")
    return MultimodalPart(
        role=value["role"],
        content=ArtifactBlobRef(
            content["content_sha256"],
            content["size_bytes"],
            content["media_type"],
        ),
        modality_id=value.get("modality_id"),
        encoding=value.get("encoding"),
        part_id=value.get("part_id"),
        sequence_index=value.get("sequence_index", 0),
        timestamp_ns=value.get("timestamp_ns"),
        duration_ns=value.get("duration_ns"),
        coordinate_frame=value.get("coordinate_frame"),
        metadata=value.get("metadata") or {},
        source_refs=tuple(value.get("source_refs") or ()),
    )


def _method_payload(value: MultimodalMethodSpec | None):
    if value is None:
        return None
    return {
        "method_id":value.method_id,
        "revision":value.revision,
        "input_schema_id":value.input_schema_id,
        "output_schema_id":value.output_schema_id,
        "input_modalities":value.input_modalities,
        "output_modalities":value.output_modalities,
        "parameters":value.parameters,
    }


def _method_from_payload(value: object) -> MultimodalMethodSpec | None:
    if value is None:
        return None
    if not isinstance(value,dict):
        raise TypeError("multimodal method payload must be an object")
    return MultimodalMethodSpec(
        method_id=value["method_id"],
        revision=value["revision"],
        input_schema_id=value["input_schema_id"],
        output_schema_id=value["output_schema_id"],
        input_modalities=tuple(value.get("input_modalities") or ()),
        output_modalities=tuple(value.get("output_modalities") or ()),
        parameters=value.get("parameters") or {},
    )


class _MultimodalCodec(QualifiedCapabilityCodec):
    capability_id="multimodal-inference"
    input_schema_id="model.multimodal.request.v1"
    output_schema_id="model.multimodal.response.v1"

    def encode(self,payload):
        if not isinstance(payload,MultimodalRequest):
            raise TypeError("multimodal capability requires MultimodalRequest")
        return {
            "parts":tuple(_part_payload(x) for x in payload.parts),
            "instruction":payload.instruction,
            "method":_method_payload(payload.method),
            "metadata":payload.metadata,
        }

    def source_artifact_refs(self,payload):
        if not isinstance(payload,MultimodalRequest):
            raise TypeError("multimodal capability requires MultimodalRequest")
        refs=[]
        for part in payload.parts:
            refs.append(part.content.content_sha256)
            refs.extend(part.source_refs)
        return tuple(dict.fromkeys(refs))

    def decode(self,payload,*,binding,request):
        if not isinstance(request,MultimodalRequest):
            raise TypeError("multimodal decode requires MultimodalRequest")
        value=thaw_json(payload)
        if not isinstance(value,dict):
            raise TypeError("multimodal endpoint payload is invalid")
        method=_method_from_payload(value.get("method"))
        if request.method is None:
            if method is not None:
                raise ValueError("multimodal response introduced unrequested method semantics")
        else:
            if method is None:
                method=request.method
            elif method.digest() != request.method.digest():
                raise ValueError("multimodal response method drift")
        return MultimodalResponse(
            model_revision=binding.model.revision,
            text=value.get("text"),
            parts=tuple(_part_from_payload(x) for x in value.get("parts") or ()),
            method=method,
            metadata=value.get("metadata") or {},
        )


def _action_payload(value: WorldModelActionTrajectory | None):
    if value is None:
        return None
    return {
        "action_schema_id":value.action_schema_id,
        "steps":tuple({
            "step_index":x.step_index,
            "payload":x.payload,
            "timestamp_ns":x.timestamp_ns,
            "duration_ns":x.duration_ns,
        } for x in value.steps),
        "action_rate_hz":value.action_rate_hz,
        "embodiment_id":value.embodiment_id,
    }


def _action_from_payload(value: object) -> WorldModelActionTrajectory | None:
    if value is None:
        return None
    if not isinstance(value,dict):
        raise TypeError("world-model action trajectory payload must be an object")
    return WorldModelActionTrajectory(
        action_schema_id=value["action_schema_id"],
        steps=tuple(
            WorldModelActionStep(
                step_index=x["step_index"],
                payload=x["payload"],
                timestamp_ns=x.get("timestamp_ns"),
                duration_ns=x.get("duration_ns"),
            )
            for x in value.get("steps") or ()
        ),
        action_rate_hz=value.get("action_rate_hz"),
        embodiment_id=value.get("embodiment_id"),
    )


class _WorldModelCodec(QualifiedCapabilityCodec):
    capability_id="world-model"
    input_schema_id="model.world-model.input.v1"
    output_schema_id="model.world-model.output.v1"

    def encode(self,payload):
        if not isinstance(payload,WorldModelInput):
            raise TypeError("world-model capability requires WorldModelInput")
        return {
            "mode":payload.mode.value,
            "observations":tuple(_part_payload(x) for x in payload.observations),
            "task_prompt":payload.task_prompt,
            "action_trajectory":_action_payload(payload.action_trajectory),
            "state":payload.state,
            "rollout_horizon":payload.rollout_horizon,
            "candidates":payload.candidates,
            "parameters":payload.parameters,
        }

    def source_artifact_refs(self,payload):
        if not isinstance(payload,WorldModelInput):
            raise TypeError("world-model capability requires WorldModelInput")
        refs=[]
        for part in payload.observations:
            refs.append(part.content.content_sha256)
            refs.extend(part.source_refs)
        return tuple(dict.fromkeys(refs))

    def decode(self,payload,*,binding,request):
        if not isinstance(request,WorldModelInput):
            raise TypeError("world-model decode requires WorldModelInput")
        value=thaw_json(payload)
        if not isinstance(value,dict) or not isinstance(value.get("rollouts"),(list,tuple)):
            raise TypeError("world-model endpoint payload is invalid")
        mode=WorldModelMode(value.get("mode",request.mode.value))
        if mode is not request.mode:
            raise ValueError("world-model response mode drift")
        rollouts=[]
        for row in value["rollouts"]:
            if not isinstance(row,dict):
                raise TypeError("world-model rollout payload must be an object")
            rollouts.append(WorldModelRollout(
                media=tuple(_part_from_payload(x) for x in row.get("media") or ()),
                predicted_actions=_action_from_payload(row.get("predicted_actions")),
                predicted_state=row.get("predicted_state"),
                score=row.get("score"),
                terminated=row.get("terminated"),
                metadata=row.get("metadata") or {},
            ))
        if len(rollouts) != request.candidates:
            raise ValueError("world-model response candidate cardinality drift")
        return WorldModelOutput(
            mode=mode,
            model_revision=binding.model.revision,
            rollouts=tuple(rollouts),
            primary_index=int(value.get("primary_index",0)),
            metadata=value.get("metadata") or {},
        )


_DEFAULT_CODECS=(
    _EmbeddingCodec(),
    _ScoringCodec(),
    _RankingCodec(),
    _ValueCodec(),
    _PolicyCodec(),
    _MultimodalCodec(),
    _WorldModelCodec(),
)


@dataclass(slots=True)
class _QualifiedOperationCapabilityClient(Generic[InputT,OutputT]):
    requirement: ModelCapabilityRequirement
    binding: ProjectModelBinding
    _pool: AdaptiveModelEndpointPoolPort
    _requests: ModelRequestRecorderPort
    _codec: QualifiedCapabilityCodec

    def invoke(self,request: ModelCapabilityInvocation[InputT]) -> ModelCapabilityResponse[OutputT]:
        if not isinstance(request,ModelCapabilityInvocation):
            raise TypeError("qualified model capability invocation must be typed")
        if request.requirement_digest != self.requirement.digest():
            raise ValueError("qualified capability request requirement provenance drift")
        if request.capability_id != self.requirement.capability_id:
            raise ValueError("qualified capability request capability drift")
        if request.input_schema_id != self.requirement.input_schema_id:
            raise ValueError("qualified capability request input schema drift")
        body=self._codec.encode(request.payload)
        envelope=self._requests.record_operation(
            request_id=request.invocation_id,
            context=request.context,
            role=self.binding.role,
            model=self.binding.model,
            capability_id=self.requirement.capability_id,
            input_schema_id=self.requirement.input_schema_id,
            output_schema_id=self.requirement.output_schema_id,
            request_body=body,
            source_artifact_refs=self._codec.source_artifact_refs(request.payload),
        )
        self._requests.verify_visible_request(envelope,body)
        dispatch=self._pool.complete(envelope,body)
        if dispatch.response.request_id != request.invocation_id:
            raise ValueError("qualified capability endpoint request identity drift")
        output=self._codec.decode(
            dispatch.response.payload,
            binding=self.binding,
            request=request.payload,
        )
        if output.schema_id != self.requirement.output_schema_id:
            raise ValueError("qualified capability output schema drift")
        return ModelCapabilityResponse(
            request_digest=request.request_digest,
            binding_digest=self.binding.digest(),
            output_schema_id=self.requirement.output_schema_id,
            output=output,
            operational_deployment_id=dispatch.request.deployment_id,
            operational_deployment_generation=dispatch.request.deployment_generation,
            operational_dispatch_digest=dispatch.dispatch_digest,
        )


class _QualifiedOperationCapabilityProvider:
    def __init__(
        self,
        *,
        profile: ModelProviderProfile,
        bindings,
        replica_pool_factory: ReplicaPoolFactory,
        model_requests: ModelRequestRecorderPort,
        codecs: tuple[QualifiedCapabilityCodec,...]=(),
    ) -> None:
        if not isinstance(profile,ModelProviderProfile):
            raise TypeError("qualified capability provider profile must be typed")
        if not isinstance(model_requests,ModelRequestRecorderPort):
            raise TypeError("qualified capability provider requires ModelRequestRecorderPort")
        self._profile=profile
        self._bindings=bindings
        self._replica_pool_factory=replica_pool_factory
        self._requests=model_requests
        registry={}
        for codec in (*_DEFAULT_CODECS,*codecs):
            key=(codec.capability_id,codec.input_schema_id,codec.output_schema_id)
            if key in registry:
                raise ValueError(f"duplicate qualified capability codec: {key}")
            registry[key]=codec
        self._codecs=registry
        self._cache: SingleFlightCache[ProjectModelCapabilityClientPort] = SingleFlightCache()

    @property
    def profile(self):
        return self._profile

    @property
    def capability_id(self):
        return "*"

    def diagnose(self,requirement):
        if not isinstance(requirement,ModelCapabilityRequirement):
            raise TypeError("qualified capability requirement must be typed")
        key=(requirement.capability_id,requirement.input_schema_id,requirement.output_schema_id)
        if key not in self._codecs:
            from .binding import binding_diagnostic
            from noetrium_platform.capabilities.model.api.project import ModelBindingDiagnosticCode
            return (binding_diagnostic(
                self._profile,
                requirement,
                ModelBindingDiagnosticCode.CAPABILITY_PROTOCOL_UNSUPPORTED,
                "qualified model runtime has no codec for requested capability protocol",
            ),)
        _binding,diagnostics=resolve_qualified_model_requirement(
            self._profile,self._bindings,requirement
        )
        return diagnostics

    def bind_capability(self,requirement):
        if not isinstance(requirement,ModelCapabilityRequirement):
            raise TypeError("qualified capability requirement must be typed")
        if requirement.is_generation:
            raise ValueError("generation capability must use the generation codec path")
        key=(requirement.capability_id,requirement.input_schema_id,requirement.output_schema_id)
        codec=self._codecs.get(key)
        if codec is None:
            raise ValueError("qualified model runtime has no codec for requested capability protocol")
        digest=requirement.digest()

        def build() -> ProjectModelCapabilityClientPort:
            binding,diagnostics=resolve_qualified_model_requirement(
                self._profile,self._bindings,requirement
            )
            if diagnostics or binding is None:
                from noetrium_platform.capabilities.model.api.project import ModelProjectBindingError
                raise ModelProjectBindingError(diagnostics)
            project_binding=project_binding_from_qualified(
                profile=self._profile,
                requirement=requirement,
                binding=binding,
                request_tokenization_digest=None,
            )
            pool=materialize_qualified_replica_pool(
                profile=self._profile,
                requirement=requirement,
                bindings=self._bindings,
                replica_pool_factory=self._replica_pool_factory,
            )
            return _QualifiedOperationCapabilityClient(
                requirement,project_binding,pool,self._requests,codec
            )

        return self._cache.get_or_create(digest, build)



__all__=["QualifiedCapabilityCodec"]
