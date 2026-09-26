from __future__ import annotations
from research.reproductions._support import JsonObject, JsonValue, canonical_digest, thaw_json

from collections.abc import Mapping, Sequence

from noetrium.api.research_authoring import (
    CapabilityRequest,
    CapabilityResult,
    ChildFailurePolicy,
    ChildResearchMachineExecution,
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
    )

from .fidelity import FLASH_VSTREAM_REFERENCE_FIDELITY
from .memory import (
    FLASH_VSTREAM_MEMORY_PROGRAM,
    FlashVStreamInputBundle,
    flash_vstream_memory_initial_data,
)
from .source import FLASH_VSTREAM_QWEN_ICCV_COMMIT

_MEMORY_HOST_ID = "flash-vstream.dual-flash-memory"
_ANSWER_CAPABILITY = "model.multimodal.generate"
_RESPONSE_CONTRACT_ID = "flash-vstream.egoschema.structured-choice.v1"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _options(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError("Flash-VStream options must be a sequence")
    rows = tuple(_text(row, "Flash-VStream option") for row in value)
    if len(rows) != 5:
        raise ValueError("Flash-VStream EgoSchema requires exactly five options")
    return rows


def _mapping(value: object, field_name: str) -> dict[str, JsonValue]:
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must be an object")
    return decoded


def flash_vstream_method_initial_state(
    *,
    task_id: str,
    question: str,
    options: tuple[str, ...],
    input_bundle: FlashVStreamInputBundle,
) -> JsonObject:
    if not isinstance(input_bundle, FlashVStreamInputBundle):
        raise TypeError("Flash-VStream method requires FlashVStreamInputBundle")
    return {
        "source_commit": FLASH_VSTREAM_QWEN_ICCV_COMMIT,
        "task_id": _text(task_id, "Flash-VStream task_id"),
        "question": _text(question, "Flash-VStream question"),
        "options": _options(options),
        "input_bundle": input_bundle.payload(),
        "memory_result": None,
        "memory_digest": None,
        "context_memory_slot_count": None,
        "augmentation_memory_slot_count": None,
        "predicted_choice_index": None,
        "predicted_choice_text": None,
        "raw_model_output": None,
        "model_result_digest": None,
    }


def _compose_memory(request: MethodNodeRequest) -> MethodNodeResult:
    if request.child_machines is None or request.parent_machine_id is None:
        raise RuntimeError("Flash-VStream requires child MemoryMachine execution")
    bundle = FlashVStreamInputBundle.from_payload(request.state.get("input_bundle"))
    child_machine_id = f"{request.parent_machine_id}:flash-vstream-memory"
    child = request.child_machines.execute(
        ChildResearchMachineRequest(
            host_id=_MEMORY_HOST_ID,
            parent_machine_id=request.parent_machine_id,
            child_machine_id=child_machine_id,
            instance_identity={
                "source_commit": FLASH_VSTREAM_QWEN_ICCV_COMMIT,
                "memory_program_digest": FLASH_VSTREAM_MEMORY_PROGRAM.program_digest,
                "input_digest": bundle.input_digest,
                "child_registry_identity_digest": request.child_machines.identity_digest,
            },
            initial_data=flash_vstream_memory_initial_data(bundle),
            failure_policy=ChildFailurePolicy.FAIL_PARENT,
            command_id_prefix=child_machine_id,
        )
    )
    if not isinstance(child, ChildResearchMachineExecution):
        raise TypeError("Flash-VStream memory child returned invalid execution")
    if child.status.value != "completed":
        raise RuntimeError(
            "Flash-VStream memory child did not complete: "
            f"{child.status.value}"
        )
    result = _mapping(child.result, "Flash-VStream memory child result")
    context = _mapping(result.get("context_memory"), "Flash-VStream context memory")
    augmentation = _mapping(
        result.get("augmentation_memory"),
        "Flash-VStream augmentation memory",
    )
    context_slots = context.get("slot_count")
    augmentation_slots = augmentation.get("slot_count")
    if type(context_slots) is not int or context_slots < 1:
        raise ValueError("Flash-VStream context slot count is invalid")
    if type(augmentation_slots) is not int or augmentation_slots < 1:
        raise ValueError("Flash-VStream augmentation slot count is invalid")
    memory_digest = _text(result.get("memory_digest"), "Flash-VStream memory digest")
    return MethodNodeResult(
        value=result,
        state_update={
            "memory_result": result,
            "memory_digest": memory_digest,
            "context_memory_slot_count": context_slots,
            "augmentation_memory_slot_count": augmentation_slots,
        },
        next_node="answer",
        child_links=(child.link,),
        events=(
            MethodEvent(
                "flash-vstream.memory.composed",
                {
                    "memory_digest": memory_digest,
                    "context_memory_slot_count": context_slots,
                    "augmentation_memory_slot_count": augmentation_slots,
                    "child_cut_digest": child.execution.cut.cut_digest,
                },
            ),
        ),
    )


def _answer(request: MethodNodeRequest) -> MethodNodeResult:
    if request.capabilities is None:
        raise RuntimeError("Flash-VStream requires multimodal model capability")
    memory = _mapping(request.state.get("memory_result"), "Flash-VStream memory result")
    options = _options(request.state.get("options", ()))
    capability_result = request.capabilities.invoke(
        CapabilityRequest(
            capability_id=_ANSWER_CAPABILITY,
            payload={
                "task_id": _text(request.state.get("task_id"), "Flash-VStream task_id"),
                "question": _text(request.state.get("question"), "Flash-VStream question"),
                "options": options,
                "composed_memory": memory.get("composed_memory"),
                "memory_digest": request.state.get("memory_digest"),
                "memory_aware_rope": True,
                "composition_order": FLASH_VSTREAM_REFERENCE_FIDELITY.composition_order,
                "source_commit": FLASH_VSTREAM_QWEN_ICCV_COMMIT,
                "response_contract": _RESPONSE_CONTRACT_ID,
            },
            context=request.context,
        )
    )
    if not isinstance(capability_result, CapabilityResult):
        raise TypeError("Flash-VStream model capability returned invalid result")
    if capability_result.capability_id != _ANSWER_CAPABILITY:
        raise ValueError("Flash-VStream model capability identity drifted")
    decoded = _mapping(capability_result.payload, "Flash-VStream model result")
    choice_index = decoded.get("choice_index")
    if type(choice_index) is not int or not 0 <= choice_index < len(options):
        raise ValueError(
            "Flash-VStream model result must provide structured choice_index in [0,4]"
        )
    raw_output = decoded.get("raw_output")
    if raw_output is not None and type(raw_output) is not str:
        raise TypeError("Flash-VStream raw model output must be text when provided")
    result_digest = capability_result.digest()
    return MethodNodeResult(
        value={
            "choice_index": choice_index,
            "choice_text": options[choice_index],
            "model_result_digest": result_digest,
        },
        state_update={
            "predicted_choice_index": choice_index,
            "predicted_choice_text": options[choice_index],
            "raw_model_output": raw_output,
            "model_result_digest": result_digest,
        },
        next_node="return",
        events=(
            MethodEvent(
                "flash-vstream.answer.generated",
                {
                    "response_contract": _RESPONSE_CONTRACT_ID,
                    "choice_index": choice_index,
                    "model_result_digest": result_digest,
                    "provider_generation": capability_result.generation,
                },
            ),
        ),
    )


def _return(request: MethodNodeRequest) -> MethodNodeResult:
    choice_index = request.state.get("predicted_choice_index")
    if type(choice_index) is not int or not 0 <= choice_index < 5:
        raise RuntimeError("Flash-VStream predicted choice is missing")
    choice_text = _text(
        request.state.get("predicted_choice_text"),
        "Flash-VStream predicted choice text",
    )
    return MethodNodeResult(
        value={
            "source_commit": FLASH_VSTREAM_QWEN_ICCV_COMMIT,
            "task_id": request.state.get("task_id"),
            "predicted_choice_index": choice_index,
            "predicted_choice_text": choice_text,
            "memory_digest": request.state.get("memory_digest"),
            "context_memory_slot_count": request.state.get("context_memory_slot_count"),
            "augmentation_memory_slot_count": request.state.get("augmentation_memory_slot_count"),
            "model_result_digest": request.state.get("model_result_digest"),
            "raw_model_output": request.state.get("raw_model_output"),
        }
    )


def build_flash_vstream_method_program() -> MethodProgram:
    fidelity = FLASH_VSTREAM_REFERENCE_FIDELITY
    configuration: JsonObject = {
        "source_commit": FLASH_VSTREAM_QWEN_ICCV_COMMIT,
        "memory_program_digest": FLASH_VSTREAM_MEMORY_PROGRAM.program_digest,
        "answer_capability": _ANSWER_CAPABILITY,
        "response_contract": _RESPONSE_CONTRACT_ID,
        "raw_text_parser": None,
        "context_memory": {
            "configured_length": fidelity.temporal_config_length,
            "effective_packed_slots": fidelity.temporal_effective_packed_slots,
            "method": fidelity.temporal_method,
        },
        "augmentation_memory": {
            "configured_length": fidelity.spatial_config_length,
            "effective_packed_slots": fidelity.spatial_effective_packed_slots,
            "method": fidelity.spatial_method,
            "metric": fidelity.spatial_retrieval_metric,
        },
        "memory_aware_rope": fidelity.memory_aware_rope_enabled,
        "composition_order": fidelity.composition_order,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="flash-vstream-streaming-multimodal-memory",
            implementation_version=FLASH_VSTREAM_QWEN_ICCV_COMMIT[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="flash-vstream.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="compose_memory")
    builder.compute(
        "compose_memory",
        "flash-vstream.memory.execute",
        _compose_memory,
        ("answer",),
        evidence_obligations=("flash-vstream.memory-child-cut",),
    )
    builder.compute(
        "answer",
        "flash-vstream.multimodal.answer",
        _answer,
        ("return",),
        evidence_obligations=("flash-vstream.structured-answer-receipt",),
    )
    builder.return_node("return", "flash-vstream.result", _return)
    return builder.build(
        configuration=configuration,
        required_runtime_ports=(MethodRuntimePort.CHILD_MACHINES,),
        required_capabilities=(_ANSWER_CAPABILITY,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "flash-vstream.memory-child-cut",
            "flash-vstream.immutable-tensor-inputs",
            "flash-vstream.structured-answer-receipt",
        ),
        metric_names=(
            "context_memory_slot_count",
            "augmentation_memory_slot_count",
            "multiple_choice_accuracy",
        ),
        artifact_kinds=(
            "flash_vstream_video_feature_tensor",
            "flash_vstream_memory_receipt",
        ),
    )


FLASH_VSTREAM_METHOD_PROGRAM = build_flash_vstream_method_program()


__all__ = [
    "FLASH_VSTREAM_METHOD_PROGRAM",
    "build_flash_vstream_method_program",
    "flash_vstream_method_initial_state",
]
