from __future__ import annotations

from pathlib import Path

from noetrium_platform.capabilities.model.request.api import (
    ModelOperationEnvelope,
)
from noetrium_platform.capabilities.model.request.runtime import (
    SQLiteModelRequestLedger,
    ReconstructableModelRequestRecorder,
)
from noetrium_platform.evidence.artifact.content.providers import (
    DirectoryArtifactBlobStore,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    ImmutableModelIdentity,
)


def _model() -> ImmutableModelIdentity:
    return ImmutableModelIdentity(
        "world",
        "world-model",
        "rev-1",
        "cosmos",
        "1",
        "bfloat16",
        None,
        32768,
    )


def test_model_operation_round_trips_through_single_invocation_ledger(tmp_path: Path) -> None:
    content=DirectoryArtifactBlobStore(tmp_path/"content")
    ledger=SQLiteModelRequestLedger(tmp_path/"requests")
    recorder=ReconstructableModelRequestRecorder(content,ledger)
    body={
        "mode":"forward_dynamics",
        "model":"world-model",
        "input":{"state":{"x":1}},
    }
    envelope=recorder.record_operation(
        request_id="world-op-1",
        context=ExecutionContext("run","trace","span"),
        role="world",
        model=_model(),
        capability_id="world-model",
        input_schema_id="model.world-model.input.v1",
        output_schema_id="model.world-model.output.v1",
        request_body=body,
        source_artifact_refs=("sha256:frame0",),
        source_state_refs=("state:0",),
    )
    assert isinstance(envelope,ModelOperationEnvelope)
    assert envelope.capability_id=="world-model"
    loaded=ledger.get("world-op-1")
    assert loaded==envelope
    reconstructed=recorder.reconstruct_request_body(loaded)
    assert reconstructed["mode"]=="forward_dynamics"
    assert reconstructed["input"]["state"]["x"]==1
    recorder.verify_visible_request(loaded,body)


def test_model_operation_id_cannot_be_rebound(tmp_path: Path) -> None:
    content=DirectoryArtifactBlobStore(tmp_path/"content")
    ledger=SQLiteModelRequestLedger(tmp_path/"requests")
    recorder=ReconstructableModelRequestRecorder(content,ledger)
    common=dict(
        request_id="op-fixed",
        context=ExecutionContext("run","trace","span"),
        role="vision",
        model=_model(),
        capability_id="multimodal",
        input_schema_id="model.multimodal.input.v1",
        output_schema_id="model.multimodal.output.v1",
    )
    recorder.record_operation(
        **common,
        request_body={"model":"world-model","messages":[]},
    )
    try:
        recorder.record_operation(
            **common,
            request_body={"model":"world-model","messages":[{"role":"user","content":"different"}]},
        )
    except RuntimeError as exc:
        assert "already bound" in str(exc)
    else:
        raise AssertionError("operation request_id was rebound")


def test_generation_and_operation_share_one_directory_without_schema_confusion(tmp_path: Path) -> None:
    content=DirectoryArtifactBlobStore(tmp_path/"content")
    ledger=SQLiteModelRequestLedger(tmp_path/"requests")
    recorder=ReconstructableModelRequestRecorder(content,ledger)
    generation=recorder.record(
        request_id="gen-1",
        context=ExecutionContext("run","trace","span"),
        role="planner",
        model=_model(),
        prompt_generation_id="g1",
        prompt_id="p1",
        prompt_digest="a"*64,
        request_body={"model":"world-model","messages":[{"role":"user","content":"x"}]},
    )
    operation=recorder.record_operation(
        request_id="op-1",
        context=ExecutionContext("run","trace","span2"),
        role="vision",
        model=_model(),
        capability_id="multimodal",
        input_schema_id="model.multimodal.input.v1",
        output_schema_id="model.multimodal.output.v1",
        request_body={"model":"world-model","messages":[{"role":"user","content":"image"}]},
    )
    assert ledger.get("gen-1")==generation
    assert ledger.get("op-1")==operation
