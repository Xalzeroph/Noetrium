from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
    capability_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import EffectClass, JsonValue, freeze_json
from noetrium_platform.research.experimentation.run.api import (
    RunArtifactKind,
    RunArtifactSealedError,
    RunArtifactStorePort,
)

_CAPABILITY_ID = "artifact.publish"
_REQUEST_SCHEMA = "noetrium.run-artifact.publish.request.v1"
_RESULT_SCHEMA = "noetrium.run-artifact.publish.result.v1"


class RunArtifactPublishCapabilityBinding:
    """Content-addressed immutable publication through RunArtifactStore authority."""

    def __init__(
        self,
        store: RunArtifactStorePort,
        *,
        capability_id: str = _CAPABILITY_ID,
    ) -> None:
        if not isinstance(store, RunArtifactStorePort):
            raise TypeError("artifact publish capability requires RunArtifactStorePort")
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise ValueError("artifact publish capability_id must be non-empty")
        self._store = store
        self._descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            interface_version="1",
            request_schema=_REQUEST_SCHEMA,
            result_schema=_RESULT_SCHEMA,
            effect_class=EffectClass.IDEMPOTENT,
            deterministic=True,
        )

    @property
    def capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        return (self._descriptor,)

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        if capability_id != self._descriptor.capability_id:
            raise KeyError(capability_id)
        return self._descriptor

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        if request.capability_id != self._descriptor.capability_id:
            raise KeyError(request.capability_id)
        payload = request.payload
        if not isinstance(payload, Mapping):
            raise TypeError("artifact publish payload must be a mapping")
        artifact_type = payload.get("artifact_type")
        if not isinstance(artifact_type, str) or not artifact_type.strip():
            raise ValueError("artifact publish requires artifact_type")
        media_type = payload.get("media_type")
        if media_type not in {"text/plain", "application/json"}:
            raise ValueError("artifact publish media_type must be text/plain or application/json")
        if "content" not in payload:
            raise ValueError("artifact publish requires content")

        content = payload["content"]
        if media_type == "text/plain":
            if not isinstance(content, str):
                raise TypeError("text artifact content must be text")
            body = content
            suffix = "txt"
        else:
            value = freeze_json(content)
            body = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ) + "\n"
            suffix = "json"

        encoded = body.encode("utf-8")
        content_sha256 = hashlib.sha256(encoded).hexdigest()
        safe_type = "".join(
            char if char.isalnum() or char in "._-" else "-"
            for char in artifact_type.strip()
        ).strip(".-")
        if not safe_type:
            raise ValueError("artifact_type has no safe canonical characters")
        artifact_ref = (
            f"method-artifacts/{safe_type}/"
            f"{content_sha256}.{suffix}"
        )

        try:
            self._store.publish_text(
                artifact_ref,
                body,
                kind=RunArtifactKind.METHOD,
            )
        except RunArtifactSealedError:
            # Content-addressed identity makes this a safe retry. finalize()
            # re-reads and verifies the durable seal before returning it.
            pass

        receipt = self._store.finalize(
            artifact_ref,
            kind=RunArtifactKind.METHOD,
            record_stream=False,
        )
        receipt = self._store.verify_finalized(receipt)
        if receipt.content_sha256 != content_sha256:
            raise ValueError("artifact publish durable content digest mismatch")

        request_digest = capability_request_digest(request)
        return CapabilityResult(
            capability_id=self._descriptor.capability_id,
            payload={
                "artifact_type": artifact_type,
                "media_type": media_type,
                "artifact_ref": receipt.artifact_ref,
                "generation": receipt.generation,
                "content_sha256": receipt.content_sha256,
                "byte_size": receipt.byte_size,
            },
            generation=receipt.generation,
            artifacts=(receipt.artifact_ref,),
            diagnostics={
                "immutable": True,
                "content_addressed": True,
            },
            request_digest=request_digest,
        )


__all__ = ["RunArtifactPublishCapabilityBinding"]
