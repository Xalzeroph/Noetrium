from __future__ import annotations

import pytest

from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity


_SHA = "a" * 64
_CONTEXT = ExecutionContext("run:1", "trace:1", "span:1")
_MODEL = ImmutableModelIdentity(
    "planner", "model:1", "revision:1", "vllm", "1.0", "bfloat16", None, 8192
)
_BODY = ArtifactBlobRef("b" * 64, 10, "application/json")


def _envelope(**overrides: object) -> ModelRequestEnvelope:
    values: dict[str, object] = {
        "schema_version": "model-request.v1",
        "request_id": "request:1",
        "context": _CONTEXT,
        "role": "planner",
        "model": _MODEL,
        "prompt_generation_id": "generation:1",
        "prompt_id": "planner.prompt",
        "prompt_digest": _SHA,
        "request_body": _BODY,
    }
    values.update(overrides)
    return ModelRequestEnvelope(**values)  # type: ignore[arg-type]

def test_content_ref_requires_exact_lowercase_sha_and_integer_size() -> None:
    with pytest.raises(ValueError):
        ArtifactBlobRef("A" * 64, 1, "application/json")
    with pytest.raises(ValueError):
        ArtifactBlobRef("a" * 64, True, "application/json")
    with pytest.raises(ValueError):
        ArtifactBlobRef("a" * 64, 1, "")


def test_request_envelope_rejects_unknown_schema_and_non_sha_prompt_digest() -> None:
    with pytest.raises(ValueError):
        _envelope(schema_version="model-request.v0")
    with pytest.raises(ValueError):
        _envelope(prompt_digest="not-a-digest")


def test_request_envelope_requires_typed_context_model_and_content_refs() -> None:
    with pytest.raises(ValueError):
        _envelope(context={"run_id": "run:1"})
    with pytest.raises(ValueError):
        _envelope(model="model:1")
    with pytest.raises(ValueError):
        _envelope(request_body={"sha256": "b" * 64})

def test_request_envelope_rejects_invalid_model_identity_projection() -> None:
    invalid_model = ImmutableModelIdentity(
        "planner", "", "revision:1", "vllm", "1.0", "bfloat16", None, 8192
    )
    with pytest.raises(ValueError):
        _envelope(model=invalid_model)


def test_request_envelope_rejects_non_tuple_or_empty_source_refs() -> None:
    with pytest.raises(ValueError):
        _envelope(source_artifact_refs=["artifact:1"])
    with pytest.raises(ValueError):
        _envelope(source_state_refs=("",))


def test_request_envelope_digest_is_reproducible_and_tamper_checked() -> None:
    envelope = _envelope(
        source_artifact_refs=("artifact:1",),
        source_state_refs=("state:1",),
    )
    assert len(envelope.envelope_digest) == 64
    assert envelope == _envelope(
        source_artifact_refs=("artifact:1",),
        source_state_refs=("state:1",),
        envelope_digest=envelope.envelope_digest,
    )
    with pytest.raises(ValueError):
        _envelope(envelope_digest="c" * 64)