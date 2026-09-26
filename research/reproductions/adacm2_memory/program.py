from __future__ import annotations
from research.reproductions._support import JsonObject, JsonValue, canonical_digest, thaw_json

from collections.abc import Mapping, Sequence

from noetrium.api.research_authoring import (
    CapabilityRequest,
    CapabilityResult,
    ChildFailurePolicy,
    ChildResearchMachineRequest,
    MethodEvent,
    MethodExecutionClass,
    MethodIdentity,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
    MethodProgramIdentity,
    MethodRuntimePort,
    TensorContentRef,
    )

from .fidelity import (
    ADACM2_REFERENCE_FIDELITY,
    AdaCM2PartitionInterpretation,
)
from .memory import (
    ADACM2_MEMORY_PROGRAM,
    adacm2_memory_initial_data,
)

_MEMORY_HOST_ID = "adacm2.cross-modal-kv-memory"
_INFERENCE_CAPABILITY = "model.multimodal.generate"
_RESPONSE_CONTRACT_ID = "adacm2.lvu.structured-prediction.v1"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _mapping(value: object, field_name: str) -> dict[str, JsonValue]:
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must be an object")
    return decoded


def _sequence(value: object, field_name: str) -> tuple[JsonValue, ...]:
    decoded = thaw_json(value)
    if isinstance(decoded, (str, bytes, bytearray)) or not isinstance(
        decoded, (tuple, list)
    ):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(decoded)


def _tensor_ref(value: object, field_name: str) -> TensorContentRef:
    decoded = _mapping(value, field_name)
    return TensorContentRef.from_payload(decoded)


def _event(kind: str, payload: Mapping[str, JsonValue]) -> JsonObject:
    return {
        "event": {
            "kind": kind,
            "payload": dict(payload),
            "source": "adacm2.method-program",
        }
    }


def adacm2_method_initial_state(
    *,
    task_id: str,
    task_family: str,
    interpretation: AdaCM2PartitionInterpretation,
    query_text_ref: TensorContentRef,
    frame_updates: tuple[JsonObject, ...],
    inference_payload: JsonObject,
) -> JsonObject:
    if not isinstance(interpretation, AdaCM2PartitionInterpretation):
        raise TypeError("AdaCM2 interpretation must be typed")
    if not isinstance(query_text_ref, TensorContentRef):
        raise TypeError("AdaCM2 method requires query TensorContentRef")
    if type(frame_updates) is not tuple or not frame_updates:
        raise ValueError("AdaCM2 method requires at least one frame update")
    normalized_updates: list[JsonObject] = []
    for index, row in enumerate(frame_updates):
        decoded = _mapping(row, f"AdaCM2 frame update {index}")
        layer_id = _text(decoded.get("layer_id"), "AdaCM2 layer_id")
        key_ref = _tensor_ref(decoded.get("key_ref"), "AdaCM2 frame key_ref")
        value_ref = _tensor_ref(decoded.get("value_ref"), "AdaCM2 frame value_ref")
        normalized_updates.append(
            {
                "layer_id": layer_id,
                "key_ref": key_ref.payload(),
                "value_ref": value_ref.payload(),
            }
        )
    if not isinstance(inference_payload, Mapping):
        raise TypeError("AdaCM2 inference_payload must be an object")
    return {
        "task_id": _text(task_id, "AdaCM2 task_id"),
        "task_family": _text(task_family, "AdaCM2 task_family"),
        "interpretation": interpretation.value,
        "query_text_ref": query_text_ref.payload(),
        "frame_updates": tuple(normalized_updates),
        "inference_payload": dict(inference_payload),
        "memory_snapshot": None,
        "memory_cut_digest": None,
        "peak_cache_length": 0,
        "prediction": None,
        "raw_model_output": None,
        "model_result_digest": None,
    }


def _stream_memory(request: MethodNodeRequest) -> MethodNodeResult:
    if request.child_machines is None or request.parent_machine_id is None:
        raise RuntimeError("AdaCM2 requires child MemoryMachine runtime")
    interpretation = AdaCM2PartitionInterpretation(
        _text(request.state.get("interpretation"), "AdaCM2 interpretation")
    )
    query_ref = _tensor_ref(
        request.state.get("query_text_ref"),
        "AdaCM2 query_text_ref",
    )
    initial_data = adacm2_memory_initial_data(
        query_text_ref=query_ref,
        interpretation=interpretation,
    )
    frame_updates = _sequence(
        request.state.get("frame_updates", ()),
        "AdaCM2 frame updates",
    )
    if not frame_updates:
        raise ValueError("AdaCM2 frame update sequence cannot be empty")
    child_machine_id = f"{request.parent_machine_id}:adacm2-memory"
    instance_identity = {
        "paper": "AdaCM2 CVPR 2025",
        "memory_program_digest": ADACM2_MEMORY_PROGRAM.program_digest,
        "interpretation": interpretation.value,
        "input_digest": canonical_digest(
            {
                "task_id": request.state.get("task_id"),
                "query_text_ref": query_ref.tensor_digest,
                "frame_updates": frame_updates,
            }
        ),
        "child_registry_identity_digest": request.child_machines.identity_digest,
    }
    peak_cache_length = 0
    latest = None
    for index, row in enumerate(frame_updates):
        update = _mapping(row, f"AdaCM2 frame update {index}")
        latest = request.child_machines.step_once(
            ChildResearchMachineRequest(
                host_id=_MEMORY_HOST_ID,
                parent_machine_id=request.parent_machine_id,
                child_machine_id=child_machine_id,
                instance_identity=instance_identity,
                initial_data=initial_data,
                failure_policy=ChildFailurePolicy.FAIL_PARENT,
                payload=_event(
                    "adacm2.cache.update",
                    {
                        "layer_id": _text(
                            update.get("layer_id"),
                            "AdaCM2 layer_id",
                        ),
                        "key_ref": _mapping(
                            update.get("key_ref"),
                            "AdaCM2 frame key_ref",
                        ),
                        "value_ref": _mapping(
                            update.get("value_ref"),
                            "AdaCM2 frame value_ref",
                        ),
                    },
                ),
                command_id_prefix=f"{child_machine_id}:update:{index}",
            )
        )
        result = _mapping(latest.result, "AdaCM2 memory update result")
        cache_length = result.get("cache_length")
        if type(cache_length) is not int or cache_length < 1:
            raise ValueError("AdaCM2 memory update returned invalid cache length")
        peak_cache_length = max(peak_cache_length, cache_length)

    final = request.child_machines.step_once(
        ChildResearchMachineRequest(
            host_id=_MEMORY_HOST_ID,
            parent_machine_id=request.parent_machine_id,
            child_machine_id=child_machine_id,
            instance_identity=instance_identity,
            initial_data=initial_data,
            failure_policy=ChildFailurePolicy.FAIL_PARENT,
            payload=_event("adacm2.cache.read", {}),
            command_id_prefix=f"{child_machine_id}:read",
        )
    )
    snapshot = _mapping(final.result, "AdaCM2 memory snapshot")
    layers = _sequence(snapshot.get("layers", ()), "AdaCM2 memory layers")
    if not layers:
        raise ValueError("AdaCM2 memory snapshot must contain cache layers")
    cut_digest = final.execution.cut.cut_digest
    return MethodNodeResult(
        value=snapshot,
        state_update={
            "memory_snapshot": snapshot,
            "memory_cut_digest": cut_digest,
            "peak_cache_length": peak_cache_length,
        },
        next_node="infer",
        child_links=(final.link,),
        events=(
            MethodEvent(
                "adacm2.memory.streamed",
                {
                    "interpretation": interpretation.value,
                    "update_count": len(frame_updates),
                    "layer_count": len(layers),
                    "peak_cache_length": peak_cache_length,
                    "memory_cut_digest": cut_digest,
                },
            ),
        ),
    )


def _infer(request: MethodNodeRequest) -> MethodNodeResult:
    if request.capabilities is None:
        raise RuntimeError("AdaCM2 requires multimodal model capability")
    memory = _mapping(
        request.state.get("memory_snapshot"),
        "AdaCM2 memory snapshot",
    )
    interpretation = AdaCM2PartitionInterpretation(
        _text(request.state.get("interpretation"), "AdaCM2 interpretation")
    )
    inference_payload = _mapping(
        request.state.get("inference_payload"),
        "AdaCM2 inference payload",
    )
    result = request.capabilities.invoke(
        CapabilityRequest(
            capability_id=_INFERENCE_CAPABILITY,
            payload={
                "task_id": _text(request.state.get("task_id"), "AdaCM2 task_id"),
                "task_family": _text(
                    request.state.get("task_family"),
                    "AdaCM2 task family",
                ),
                "interpretation": interpretation.value,
                "compressed_kv_cache": memory.get("layers"),
                "memory_cut_digest": request.state.get("memory_cut_digest"),
                "inference": inference_payload,
                "response_contract": _RESPONSE_CONTRACT_ID,
                "paper_model": ADACM2_REFERENCE_FIDELITY.llm,
                "visual_encoder": ADACM2_REFERENCE_FIDELITY.visual_encoder,
                "qformer_initialization": (
                    ADACM2_REFERENCE_FIDELITY.qformer_initialization
                ),
            },
            context=request.context,
        )
    )
    if not isinstance(result, CapabilityResult):
        raise TypeError("AdaCM2 model capability returned invalid result")
    if result.capability_id != _INFERENCE_CAPABILITY:
        raise ValueError("AdaCM2 model capability identity drifted")
    payload = _mapping(result.payload, "AdaCM2 model result")
    if "prediction" not in payload:
        raise ValueError(
            "AdaCM2 model result must provide structured prediction"
        )
    prediction = payload["prediction"]
    raw_output = payload.get("raw_output")
    if raw_output is not None and type(raw_output) is not str:
        raise TypeError("AdaCM2 raw model output must be text when provided")
    digest = result.digest()
    return MethodNodeResult(
        value={
            "prediction": prediction,
            "model_result_digest": digest,
        },
        state_update={
            "prediction": prediction,
            "raw_model_output": raw_output,
            "model_result_digest": digest,
        },
        next_node="return",
        events=(
            MethodEvent(
                "adacm2.prediction.generated",
                {
                    "interpretation": interpretation.value,
                    "response_contract": _RESPONSE_CONTRACT_ID,
                    "model_result_digest": digest,
                    "provider_generation": result.generation,
                },
            ),
        ),
    )


def _return(request: MethodNodeRequest) -> MethodNodeResult:
    if request.state.get("prediction") is None:
        raise RuntimeError("AdaCM2 prediction is missing")
    interpretation = AdaCM2PartitionInterpretation(
        _text(request.state.get("interpretation"), "AdaCM2 interpretation")
    )
    return MethodNodeResult(
        value={
            "task_id": request.state.get("task_id"),
            "task_family": request.state.get("task_family"),
            "interpretation": interpretation.value,
            "prediction": request.state.get("prediction"),
            "raw_model_output": request.state.get("raw_model_output"),
            "model_result_digest": request.state.get("model_result_digest"),
            "memory_cut_digest": request.state.get("memory_cut_digest"),
            "peak_cache_length": request.state.get("peak_cache_length"),
        }
    )


def build_adacm2_method_program() -> MethodProgram:
    fidelity = ADACM2_REFERENCE_FIDELITY
    configuration: JsonObject = {
        "paper_revision": fidelity.source_revision,
        "memory_program_digest": ADACM2_MEMORY_PROGRAM.program_digest,
        "treatment_parameter": "interpretation",
        "supported_interpretations": tuple(
            row.value for row in AdaCM2PartitionInterpretation
        ),
        "alpha": fidelity.alpha,
        "beta": fidelity.beta,
        "frame_sampling_fps": fidelity.frame_sampling_fps,
        "visual_encoder": fidelity.visual_encoder,
        "qformer_initialization": fidelity.qformer_initialization,
        "llm": fidelity.llm,
        "inference_capability": _INFERENCE_CAPABILITY,
        "response_contract": _RESPONSE_CONTRACT_ID,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="adacm2-adaptive-cross-modal-memory",
            implementation_version="cvpr2025",
            abi_version="noetrium.method-machine.v1",
            schema_version="adacm2.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="stream_memory")
    builder.compute(
        "stream_memory",
        "adacm2.memory.stream",
        _stream_memory,
        ("infer",),
        evidence_obligations=("adacm2.memory-machine-cut",),
    )
    builder.compute(
        "infer",
        "adacm2.multimodal.infer",
        _infer,
        ("return",),
        evidence_obligations=("adacm2.model-inference-receipt",),
    )
    builder.return_node("return", "adacm2.result", _return)
    return builder.build(
        configuration=configuration,
        required_runtime_ports=(MethodRuntimePort.CHILD_MACHINES,),
        required_capabilities=(_INFERENCE_CAPABILITY,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "adacm2.memory-machine-cut",
            "adacm2.immutable-tensor-inputs",
            "adacm2.model-inference-receipt",
        ),
        metric_names=(
            "task_accuracy",
            "peak_cache_length",
            "cache_retention_ratio",
            "paper_stated_retention_factor",
        ),
        artifact_kinds=(
            "adacm2_query_tensor",
            "adacm2_frame_kv_tensor",
            "adacm2_memory_cut",
        ),
    )


ADACM2_METHOD_PROGRAM = build_adacm2_method_program()


__all__ = [
    "ADACM2_METHOD_PROGRAM",
    "adacm2_method_initial_state",
    "build_adacm2_method_program",
]
