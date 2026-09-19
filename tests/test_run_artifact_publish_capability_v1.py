from __future__ import annotations

from noetrium_platform.capabilities.participant.capability.api import CapabilityRequest
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, EffectClass
from noetrium_platform.research.experimentation.run.api import RunArtifactKind
from noetrium_platform.research.experimentation.run.composition import (
    RunArtifactPublishCapabilityBinding,
)
from noetrium_platform.research.experimentation.run.runtime import DirectoryRunArtifactStore


class _Actor:
    def call(self, operation, fn, /, *args, **kwargs):
        del operation
        return fn(*args, **kwargs)


def test_artifact_publish_capability_is_content_addressed_sealed_and_retry_safe(
    tmp_path,
) -> None:
    store = DirectoryRunArtifactStore(
        tmp_path,
        run_id="run-artifact-capability",
        writer_actor=_Actor(),
    )
    binding = RunArtifactPublishCapabilityBinding(store)
    descriptor = binding.describe("artifact.publish")
    assert descriptor.effect_class is EffectClass.IDEMPOTENT

    context = ExecutionContext(
        "run-artifact-capability",
        "trace",
        "span",
        task_id="task:1",
    )
    request = CapabilityRequest(
        "artifact.publish",
        {
            "artifact_type": "software.prd",
            "media_type": "text/plain",
            "content": "# Product Requirement\nBuild a calculator.\n",
        },
        context,
        "artifact:prd:1",
    )

    first = binding.invoke(request)
    second = binding.invoke(request)

    assert first.payload == second.payload
    assert first.payload["artifact_type"] == "software.prd"
    assert first.payload["artifact_ref"].startswith(
        "method-artifacts/software.prd/"
    )
    assert first.payload["content_sha256"] in first.payload["artifact_ref"]
    assert first.artifacts == (first.payload["artifact_ref"],)
    assert first.generation == second.generation

    receipt = store.finalize(
        first.payload["artifact_ref"],
        kind=RunArtifactKind.METHOD,
        record_stream=False,
    )
    assert receipt.content_sha256 == first.payload["content_sha256"]


def test_artifact_publish_json_has_canonical_content_identity(tmp_path) -> None:
    store = DirectoryRunArtifactStore(
        tmp_path,
        run_id="run-json-artifact",
        writer_actor=_Actor(),
    )
    binding = RunArtifactPublishCapabilityBinding(store)
    context = ExecutionContext("run-json-artifact", "trace", "span")

    left = binding.invoke(
        CapabilityRequest(
            "artifact.publish",
            {
                "artifact_type": "software.tasks",
                "media_type": "application/json",
                "content": {"b": 2, "a": 1},
            },
            context,
            "artifact:tasks:left",
        )
    )
    right = binding.invoke(
        CapabilityRequest(
            "artifact.publish",
            {
                "artifact_type": "software.tasks",
                "media_type": "application/json",
                "content": {"a": 1, "b": 2},
            },
            context,
            "artifact:tasks:right",
        )
    )
    assert left.payload["content_sha256"] == right.payload["content_sha256"]
    assert left.payload["artifact_ref"] == right.payload["artifact_ref"]
