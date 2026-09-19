from __future__ import annotations

import json
from collections.abc import Mapping

from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef, ArtifactBlobStorePort
from noetrium_platform.capabilities.model.serving.endpoint.api import ModelEndpointResponse
from noetrium_platform.capabilities.participant.agent.runtime.turn_facts import (
    AgentTurnFact,
    AgentTurnFactKind,
    AgentTurnFactSink,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonObject, canonical_bytes, freeze_json


def _content_ref_payload(ref: ArtifactBlobRef | None) -> JsonObject | None:
    if ref is None:
        return None
    return {
        "content_sha256": ref.content_sha256,
        "size_bytes": ref.size_bytes,
        "media_type": ref.media_type,
    }


def _content_ref(value: object) -> ArtifactBlobRef:
    if not isinstance(value, Mapping):
        raise ValueError("agent turn model content ref must be an object")
    if frozenset(value) != {"content_sha256", "size_bytes", "media_type"}:
        raise ValueError("agent turn model content ref fields mismatch")
    sha = value["content_sha256"]
    size = value["size_bytes"]
    media = value["media_type"]
    if not isinstance(sha, str) or type(size) is not int or not isinstance(media, str):
        raise ValueError("agent turn model content ref fields are invalid")
    return ArtifactBlobRef(sha, size, media)


class AgentTurnModelFactRecorder:
    """Composition bridge from model authority to Agent Turn Machine facts.

    Model request bytes remain owned by ModelRequestRecorder/CAS. Parsed model
    response content is placed in the same injected CAS so Agent Turn facts can
    reference exact recoverable content instead of copying large model text into
    Machine state or Journal metadata.
    """

    def __init__(self, facts: AgentTurnFactSink, content: ArtifactBlobStorePort) -> None:
        self._facts = facts
        self._content = content

    def record_request(self, envelope: ModelRequestEnvelope) -> AgentTurnFact:
        if not isinstance(envelope, ModelRequestEnvelope):
            raise TypeError("model request fact requires ModelRequestEnvelope")
        return self._facts.append(
            AgentTurnFactKind.MODEL_REQUEST,
            context=envelope.context,
            payload={
                "request_id": envelope.request_id,
                "envelope_digest": envelope.envelope_digest,
                "role": envelope.role,
                "model": {
                    "logical_name": envelope.model.logical_name,
                    "model_id": envelope.model.model_id,
                    "revision": envelope.model.revision,
                    "engine": envelope.model.engine,
                    "engine_version": envelope.model.engine_version,
                    "dtype": envelope.model.dtype,
                    "quantization": envelope.model.quantization,
                    "context_length": envelope.model.context_length,
                    "tokenizer_revision": envelope.model.tokenizer_revision,
                },
                "prompt_generation_id": envelope.prompt_generation_id,
                "prompt_id": envelope.prompt_id,
                "prompt_digest": envelope.prompt_digest,
                "request_body": _content_ref_payload(envelope.request_body),
                "compiled_prompt": _content_ref_payload(envelope.compiled_prompt),
                "tool_schema_bundle": _content_ref_payload(envelope.tool_schema_bundle),
                "source_artifact_refs": list(envelope.source_artifact_refs),
                "source_state_refs": list(envelope.source_state_refs),
            },
            artifact_refs=envelope.source_artifact_refs,
        )

    def record_response(
        self,
        response: ModelEndpointResponse,
        *,
        context: ExecutionContext,
    ) -> AgentTurnFact:
        if not isinstance(response, ModelEndpointResponse):
            raise TypeError("model response fact requires ModelEndpointResponse")
        document: JsonObject = {
            "request_id": response.request_id,
            "deployment_id": response.deployment_id,
            "text": response.text,
            "tool_calls": response.tool_calls,
            "finish_reason": response.finish_reason,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "usage": response.usage,
            "response_digest": response.response_digest,
        }
        ref = self._content.put(
            canonical_bytes(document),
            media_type="application/vnd.noetrium.model-response+json",
        )
        return self._facts.append(
            AgentTurnFactKind.MODEL_RESPONSE,
            context=context,
            payload={
                "request_id": response.request_id,
                "deployment_id": response.deployment_id,
                "response_digest": response.response_digest,
                "content": _content_ref_payload(ref),
                "finish_reason": response.finish_reason,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            },
        )

    def reconstruct_response(self, fact: AgentTurnFact) -> JsonObject:
        if not isinstance(fact, AgentTurnFact) or fact.kind is not AgentTurnFactKind.MODEL_RESPONSE:
            raise TypeError("response reconstruction requires MODEL_RESPONSE fact")
        ref = _content_ref(fact.payload.get("content"))
        decoded = json.loads(self._content.get(ref))
        if not isinstance(decoded, dict):
            raise RuntimeError("model response content is not an object")
        frozen = freeze_json(decoded)
        if not isinstance(frozen, Mapping):
            raise RuntimeError("model response content is not a mapping")
        if frozen.get("response_digest") != fact.payload.get("response_digest"):
            raise RuntimeError("model response content digest identity mismatch")
        return dict(frozen)


__all__ = ["AgentTurnModelFactRecorder"]
