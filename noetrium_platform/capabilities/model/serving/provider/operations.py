from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.model.request.api import ModelOperationEnvelope
from noetrium_platform.foundation.kernel.kernel import (
    JsonInput,
    JsonObject,
    JsonValue,
    canonical_bytes,
    canonical_digest,
    freeze_json,
    thaw_json,
)

from .api import ModelProviderRequestUnsupported, ModelProviderRuntimeError


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _headers(
    *,
    auth_kind: str,
    api_key: str,
) -> tuple[tuple[str, str], ...]:
    if type(api_key) is not str:
        raise TypeError("model operation api_key must be text")
    if auth_kind == "none":
        return ()
    if auth_kind in {"bearer", "bearer-optional"}:
        return () if not api_key else (("Authorization", f"Bearer {api_key}"),)
    if auth_kind == "api-key":
        return () if not api_key else (("api-key", api_key),)
    if auth_kind == "anthropic":
        values=[("anthropic-version", "2023-06-01")]
        if api_key:
            values.append(("x-api-key", api_key))
        return tuple(values)
    if auth_kind == "google-api-key":
        return () if not api_key else (("x-goog-api-key", api_key),)
    raise ModelProviderRequestUnsupported(
        f"unsupported provider authentication kind: {auth_kind}"
    )


@dataclass(frozen=True, slots=True)
class ModelProviderOperationPlan:
    capability_id: str
    protocol_id: str
    path: str
    body: JsonObject
    headers: tuple[tuple[str, str], ...] = field(repr=False, compare=False)
    correlation: JsonValue | None = None
    wire_bytes: bytes = field(init=False, repr=False, compare=False)
    plan_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.capability_id, "model operation capability_id")
        _text(self.protocol_id, "model operation protocol_id")
        if type(self.path) is not str or not self.path.startswith("/"):
            raise ValueError("model operation path must be absolute")
        if not isinstance(self.body, Mapping):
            raise TypeError("model operation body must be an object")
        object.__setattr__(self, "body", freeze_json(self.body))
        if type(self.headers) is not tuple or any(
            type(row) is not tuple
            or len(row) != 2
            or any(type(value) is not str or not value for value in row)
            for row in self.headers
        ):
            raise TypeError("model operation headers must be text pairs")
        if self.correlation is not None:
            object.__setattr__(self, "correlation", freeze_json(self.correlation))
        wire_bytes=canonical_bytes(self.body)
        object.__setattr__(self, "wire_bytes", wire_bytes)
        object.__setattr__(
            self,
            "plan_digest",
            canonical_digest({
                "schema":"noetrium.model-provider-operation-plan.v2",
                "capability_id":self.capability_id,
                "protocol_id":self.protocol_id,
                "path":self.path,
                "wire_sha256":sha256(wire_bytes).hexdigest(),
                # Values are secret; only header names belong to plan identity.
                "header_names":tuple(name.lower() for name,_ in self.headers),
                "correlation":self.correlation,
            }),
        )


@runtime_checkable
class ModelProviderOperationCodec(Protocol):
    capability_ids: tuple[str, ...]

    def plan(
        self,
        envelope: ModelOperationEnvelope,
        logical_body: Mapping[str, JsonInput],
        *,
        default_path: str,
        provider_id: str,
        auth_kind: str,
        api_key: str,
    ) -> ModelProviderOperationPlan: ...

    def decode(
        self,
        plan: ModelProviderOperationPlan,
        payload: JsonValue,
    ) -> JsonValue: ...


class _EmbeddingOperationCodec:
    capability_ids=("embedding",)

    def plan(
        self,envelope,logical_body,*,default_path,provider_id,auth_kind,api_key
    ):
        del default_path,provider_id
        texts=logical_body.get("texts")
        if (
            not isinstance(texts,Sequence)
            or isinstance(texts,(str,bytes,bytearray))
            or not texts
            or any(type(text) is not str or not text for text in texts)
        ):
            raise ModelProviderRequestUnsupported(
                "embedding operation requires non-empty text sequence"
            )
        normalize=logical_body.get("normalize",False)
        if type(normalize) is not bool:
            raise ModelProviderRequestUnsupported(
                "embedding normalize must be boolean"
            )
        body={
            "model":envelope.model.model_id,
            "input":tuple(texts),
            "encoding_format":"float",
        }
        # Normalization is semantic input. Backends that expose an explicit
        # normalization option may consume it through a provider-specific codec;
        # standard OpenAI-compatible embedding APIs return their native vectors.
        return ModelProviderOperationPlan(
            capability_id=envelope.capability_id,
            protocol_id="openai.embeddings.v1",
            path="/v1/embeddings",
            body=body,
            headers=_headers(auth_kind=auth_kind,api_key=api_key),
            correlation={"normalize":normalize},
        )

    def decode(self,plan,payload):
        if not isinstance(payload,Mapping):
            raise ModelProviderRuntimeError("embedding response must be an object")
        rows=payload.get("data")
        if not isinstance(rows,Sequence) or isinstance(rows,(str,bytes,bytearray)):
            raise ModelProviderRuntimeError("embedding response data must be an array")
        indexed={}
        for row in rows:
            if not isinstance(row,Mapping):
                raise ModelProviderRuntimeError("embedding response row must be an object")
            index=row.get("index")
            vector=row.get("embedding")
            if type(index) is not int or index < 0 or index in indexed:
                raise ModelProviderRuntimeError("embedding response index is invalid")
            if (
                not isinstance(vector,Sequence)
                or isinstance(vector,(str,bytes,bytearray))
                or not vector
            ):
                raise ModelProviderRuntimeError("embedding response vector is invalid")
            indexed[index]=tuple(vector)
        expected=tuple(range(len(indexed)))
        if tuple(sorted(indexed)) != expected:
            raise ModelProviderRuntimeError(
                "embedding response indices must be contiguous from zero"
            )
        return freeze_json({"vectors":tuple(indexed[index] for index in expected)})


class _RerankOperationCodec:
    capability_ids=("scoring","ranking")

    def plan(
        self,envelope,logical_body,*,default_path,provider_id,auth_kind,api_key
    ):
        del default_path,provider_id
        query=logical_body.get("query")
        candidates=logical_body.get("candidates")
        if type(query) is not str or not query:
            raise ModelProviderRequestUnsupported(
                f"{envelope.capability_id} operation requires query"
            )
        if (
            not isinstance(candidates,Sequence)
            or isinstance(candidates,(str,bytes,bytearray))
            or not candidates
        ):
            raise ModelProviderRequestUnsupported(
                f"{envelope.capability_id} operation requires candidates"
            )
        ids=[]
        documents=[]
        for row in candidates:
            if not isinstance(row,Mapping):
                raise ModelProviderRequestUnsupported(
                    f"{envelope.capability_id} candidate must be an object"
                )
            candidate_id=row.get("candidate_id")
            text=row.get("text")
            if type(candidate_id) is not str or not candidate_id:
                raise ModelProviderRequestUnsupported("candidate_id is required")
            if type(text) is not str or not text:
                raise ModelProviderRequestUnsupported("candidate text is required")
            ids.append(candidate_id)
            documents.append(text)
        if len(ids) != len(set(ids)):
            raise ModelProviderRequestUnsupported("candidate ids must be unique")
        body={
            "model":envelope.model.model_id,
            "query":query,
            "documents":tuple(documents),
        }
        top_k=logical_body.get("top_k")
        if envelope.capability_id == "ranking" and top_k is not None:
            if type(top_k) is not int or not 0 < top_k <= len(ids):
                raise ModelProviderRequestUnsupported("ranking top_k is invalid")
            body["top_n"]=top_k
        return ModelProviderOperationPlan(
            capability_id=envelope.capability_id,
            protocol_id="openai.rerank.v1",
            path="/v1/rerank",
            body=body,
            headers=_headers(auth_kind=auth_kind,api_key=api_key),
            correlation={"candidate_ids":tuple(ids)},
        )

    def decode(self,plan,payload):
        if not isinstance(payload,Mapping):
            raise ModelProviderRuntimeError("rerank response must be an object")
        rows=payload.get("results")
        if not isinstance(rows,Sequence) or isinstance(rows,(str,bytes,bytearray)):
            raise ModelProviderRuntimeError("rerank results must be an array")
        correlation=thaw_json(plan.correlation)
        if not isinstance(correlation,dict):
            raise ModelProviderRuntimeError("rerank correlation is missing")
        candidate_ids=correlation.get("candidate_ids")
        if not isinstance(candidate_ids,list):
            raise ModelProviderRuntimeError("rerank candidate correlation is invalid")
        seen=set()
        result=[]
        for row in rows:
            if not isinstance(row,Mapping):
                raise ModelProviderRuntimeError("rerank result must be an object")
            index=row.get("index")
            score=row.get("relevance_score")
            if (
                type(index) is not int
                or not 0 <= index < len(candidate_ids)
                or index in seen
            ):
                raise ModelProviderRuntimeError("rerank result index is invalid")
            if isinstance(score,bool) or not isinstance(score,(int,float)):
                raise ModelProviderRuntimeError("rerank score is invalid")
            seen.add(index)
            result.append({
                "candidate_id":candidate_ids[index],
                "score":float(score),
            })
        return freeze_json({"results":tuple(result)})


class _CanonicalOperationCodec:
    capability_ids=()

    def plan(
        self,envelope,logical_body,*,default_path,provider_id,auth_kind,api_key
    ):
        del provider_id
        if "model" in logical_body:
            raise ModelProviderRequestUnsupported(
                "model identity is runtime-owned for typed operations"
            )
        body={"model":envelope.model.model_id,**logical_body}
        return ModelProviderOperationPlan(
            capability_id=envelope.capability_id,
            protocol_id="noetrium.canonical-operation.v1",
            path=default_path,
            body=body,
            headers=_headers(auth_kind=auth_kind,api_key=api_key),
        )

    def decode(self,plan,payload):
        del plan
        return freeze_json(payload)


_DEFAULT_OPERATION_CODECS=(
    _EmbeddingOperationCodec(),
    _RerankOperationCodec(),
)


class NativeModelOperationProtocolRegistry:
    """Single provider-side registry for typed operation wire protocols."""

    def __init__(
        self,
        codecs: tuple[ModelProviderOperationCodec,...]=_DEFAULT_OPERATION_CODECS,
    ) -> None:
        if type(codecs) is not tuple:
            raise TypeError("model operation codecs must be a tuple")
        registry={}
        for codec in codecs:
            if not isinstance(codec,ModelProviderOperationCodec):
                raise TypeError("invalid model operation codec")
            for capability_id in codec.capability_ids:
                _text(capability_id,"model operation codec capability_id")
                if capability_id in registry:
                    raise ValueError(
                        f"duplicate model operation protocol: {capability_id}"
                    )
                registry[capability_id]=codec
        self._codecs=registry
        self._fallback=_CanonicalOperationCodec()

    def _codec(self,capability_id: str) -> ModelProviderOperationCodec:
        _text(capability_id,"model operation capability_id")
        return self._codecs.get(capability_id,self._fallback)

    def plan(
        self,
        envelope: ModelOperationEnvelope,
        logical_body: Mapping[str, JsonInput],
        *,
        default_path: str,
        provider_id: str,
        auth_kind: str,
        api_key: str,
    ) -> ModelProviderOperationPlan:
        if not isinstance(envelope,ModelOperationEnvelope):
            raise TypeError("model operation registry requires ModelOperationEnvelope")
        if not isinstance(logical_body,Mapping):
            raise TypeError("model operation logical body must be an object")
        _text(provider_id,"model operation provider_id")
        _text(auth_kind,"model operation auth_kind")
        return self._codec(envelope.capability_id).plan(
            envelope,
            logical_body,
            default_path=default_path,
            provider_id=provider_id,
            auth_kind=auth_kind,
            api_key=api_key,
        )

    def decode(
        self,
        plan: ModelProviderOperationPlan,
        payload: JsonValue,
    ) -> JsonValue:
        if not isinstance(plan,ModelProviderOperationPlan):
            raise TypeError("model operation decode requires typed plan")
        return self._codec(plan.capability_id).decode(plan,payload)


__all__=[
    "ModelProviderOperationCodec",
    "ModelProviderOperationPlan",
    "NativeModelOperationProtocolRegistry",
]
