from __future__ import annotations

import json
from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext, ImmutableModelIdentity, JsonInput, JsonObject, canonical_bytes,
    canonical_digest, canonical_text, freeze_json,
)
from noetrium_platform.substrate.api import ArtifactBlobStorePort
from noetrium_platform.capabilities.model.request.api import (
    ModelEndpointEnvelope,
    ModelOperationEnvelope,
    ModelRequestEnvelope,
    ModelRequestLedgerPort,
    ReconstructedModelRequest,
)



def _derived_compiled_prompt_text(
    body: Mapping[str, JsonInput],
) -> str | None:
    """Return the exact prompt projection already recoverable from wire body."""
    messages = body.get("messages")
    if isinstance(messages, (tuple, list)):
        return canonical_text(messages)
    prompt = body.get("prompt")
    if isinstance(prompt, str):
        return prompt
    return None

def _canonical_json(value: object) -> bytes:
    return canonical_bytes(value)


class ReconstructableModelRequestRecorder:
    """Makes model-visible request bytes durable before returning the envelope to the caller."""

    def __init__(self, content: ArtifactBlobStorePort, ledger: ModelRequestLedgerPort) -> None:
        self._content = content
        self._ledger = ledger

    def record(
        self,
        *,
        request_id: str,
        context: ExecutionContext,
        role: str,
        model: ImmutableModelIdentity,
        prompt_generation_id: str,
        prompt_id: str,
        prompt_digest: str,
        request_body: Mapping[str, JsonInput],
        compiled_prompt_text: str | None = None,
        tool_schema_bundle: JsonInput | None = None,
        source_artifact_refs: tuple[str, ...] = (),
        source_state_refs: tuple[str, ...] = (),
    ) -> ModelRequestEnvelope:
        if not isinstance(request_body, Mapping):
            raise TypeError("model-visible request body must be a mapping")
        frozen_body = freeze_json(request_body)
        frozen_tools = None if tool_schema_bundle is None else freeze_json(tool_schema_bundle)
        publications: list[tuple[str, bytes, str]] = [
            ("body", _canonical_json(frozen_body), "application/json"),
        ]
        derived_prompt = _derived_compiled_prompt_text(frozen_body)
        if (
            compiled_prompt_text is not None
            and compiled_prompt_text != derived_prompt
        ):
            publications.append(
                (
                    "prompt",
                    compiled_prompt_text.encode("utf-8"),
                    "text/plain; charset=utf-8",
                )
            )
        if frozen_tools is not None:
            publications.append(
                ("tools", _canonical_json(frozen_tools), "application/json")
            )
        refs = self._content.put_many(
            tuple(
                (payload, media_type)
                for _name, payload, media_type in publications
            )
        )
        refs_by_name = {
            name: ref
            for (name, _payload, _media_type), ref in zip(
                publications, refs, strict=True
            )
        }
        body_ref = refs_by_name["body"]
        prompt_ref = refs_by_name.get("prompt")
        tool_ref = refs_by_name.get("tools")
        envelope = ModelRequestEnvelope(
            schema_version="model-request.v1",
            request_id=request_id,
            context=context,
            role=role,
            model=model,
            prompt_generation_id=prompt_generation_id,
            prompt_id=prompt_id,
            prompt_digest=prompt_digest,
            request_body=body_ref,
            compiled_prompt=prompt_ref,
            tool_schema_bundle=tool_ref,
            source_artifact_refs=source_artifact_refs,
            source_state_refs=source_state_refs,
        )
        self._ledger.append(envelope)
        return envelope

    def record_operation(
        self,
        *,
        request_id: str,
        context: ExecutionContext,
        role: str,
        model: ImmutableModelIdentity,
        capability_id: str,
        input_schema_id: str,
        output_schema_id: str,
        request_body: Mapping[str, JsonInput],
        source_artifact_refs: tuple[str, ...] = (),
        source_state_refs: tuple[str, ...] = (),
    ) -> ModelOperationEnvelope:
        if not isinstance(request_body, Mapping):
            raise TypeError("model operation request body must be a mapping")
        frozen_body = freeze_json(request_body)
        body_ref = self._content.put(
            _canonical_json(frozen_body),
            media_type="application/json",
        )
        envelope = ModelOperationEnvelope(
            schema_version="model-operation.v1",
            request_id=request_id,
            context=context,
            role=role,
            model=model,
            capability_id=capability_id,
            input_schema_id=input_schema_id,
            output_schema_id=output_schema_id,
            request_body=body_ref,
            source_artifact_refs=source_artifact_refs,
            source_state_refs=source_state_refs,
        )
        self._ledger.append(envelope)
        return envelope

    def reconstruct(self, envelope: ModelRequestEnvelope) -> ReconstructedModelRequest:
        payload = self._content.get(envelope.request_body)
        body = json.loads(payload)
        if not isinstance(body, dict):
            raise RuntimeError("reconstructed model request body is not an object")
        compiled = (
            _derived_compiled_prompt_text(body)
            if envelope.compiled_prompt is None
            else self._content.get(envelope.compiled_prompt).decode("utf-8")
        )
        tools = None
        if envelope.tool_schema_bundle is not None:
            tools = json.loads(self._content.get(envelope.tool_schema_bundle))
        return ReconstructedModelRequest(body, compiled, tools)

    def reconstruct_request_body(
        self,
        envelope: ModelEndpointEnvelope,
    ) -> JsonObject:
        if isinstance(envelope, ModelRequestEnvelope):
            return self.reconstruct(envelope).request_body
        if not isinstance(envelope, ModelOperationEnvelope):
            raise TypeError(
                "model request reconstruction requires request/operation envelope"
            )
        payload = self._content.get(envelope.request_body)
        body = json.loads(payload)
        if not isinstance(body, dict):
            raise RuntimeError(
                "reconstructed model operation body is not an object"
            )
        return freeze_json(body)

    def close(self) -> None:
        closer = getattr(self._ledger, "close", None)
        if callable(closer):
            closer()

    def verify_visible_request(
        self,
        envelope: ModelEndpointEnvelope,
        actual_body: Mapping[str, JsonInput],
    ) -> None:
        frozen_body = freeze_json(actual_body)
        payload = _canonical_json(frozen_body)
        reference = envelope.request_body
        if (
            len(payload) != reference.size_bytes
            or canonical_digest(frozen_body) != reference.content_sha256
        ):
            raise RuntimeError(
                "model-visible request drift: actual bytes are not durably referenced"
            )


__all__ = ["ReconstructableModelRequestRecorder"]
