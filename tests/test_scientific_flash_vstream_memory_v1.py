from __future__ import annotations

from noetrium.api import MethodRuntimePort
from noetrium.api import MethodRuntimePort
from noetrium_platform.foundation.kernel.kernel import (
    MachineKind,
    canonical_digest,
    thaw_json,
)
from research.benchmarks.egoschema import (
    EGOSCHEMA_PUBLIC_COUNT,
    EGOSCHEMA_PUBLIC_SPLIT,
    EgoSchemaTaskRecord,
)
from research.reproductions.flash_vstream_memory.benchmark import (
    build_flash_vstream_egoschema_public_cut,
)
from research.reproductions.flash_vstream_memory.fidelity import (
    FLASH_VSTREAM_REFERENCE_FIDELITY,
)
from research.reproductions.flash_vstream_memory.memory import (
    FLASH_VSTREAM_MEMORY_PROGRAM,
    flash_vstream_memory_operations,
)
from research.reproductions.flash_vstream_memory.program import (
    FLASH_VSTREAM_METHOD_PROGRAM,
)
from research.reproductions.flash_vstream_memory.program import FLASH_VSTREAM_METHOD_PROGRAM
from research.reproductions.flash_vstream_memory.study import (
    build_flash_vstream_egoschema_public_study,
    flash_vstream_egoschema_trial_protocol,
)


def test_flash_vstream_dual_flash_memory_program_freezes_iccv_semantics() -> None:
    fidelity = FLASH_VSTREAM_REFERENCE_FIDELITY
    program = FLASH_VSTREAM_MEMORY_PROGRAM

    assert program.kind is MachineKind.MEMORY
    assert program.program_id == "flash-vstream.dual-flash-memory"
    assert program.entrypoint == "context_compress"
    assert fidelity.temporal_config_length == 120
    assert fidelity.temporal_effective_packed_slots == 60
    assert fidelity.temporal_method == "kmeans_ordered"
    assert fidelity.temporal_pool_size == 2
    assert fidelity.temporal_pca_dim == 32
    assert fidelity.spatial_config_length == 60
    assert fidelity.spatial_effective_packed_slots == 30
    assert fidelity.spatial_method == "klarge_retrieve"
    assert fidelity.spatial_retrieval_metric == "euclidean"
    assert fidelity.augmentation_conditioned_on_context_memory is True
    assert fidelity.memory_aware_rope_enabled is True
    assert fidelity.composition_order == (
        "augmentation_memory",
        "context_memory",
    )

    assert tuple(node.node_id for node in program.nodes) == (
        "context_compress",
        "augmentation_retrieve",
        "compose",
    )
    assert tuple(node.operation for node in program.nodes) == (
        "flash_vstream.memory.context_compress",
        "flash_vstream.memory.augmentation_retrieve",
        "flash_vstream.memory.compose",
    )
    assert tuple(node.next_node for node in program.nodes) == (
        "augmentation_retrieve",
        "compose",
        None,
    )

    context = thaw_json(program.node("context_compress").configuration)
    augmentation = thaw_json(
        program.node("augmentation_retrieve").configuration
    )
    composition = thaw_json(program.node("compose").configuration)

    assert context == {
        "configured_length": 120,
        "effective_packed_slots": 60,
        "method": "kmeans_ordered",
        "pool_size": 2,
        "memory_concern": "consolidation",
    }
    assert augmentation == {
        "configured_length": 60,
        "effective_packed_slots": 30,
        "method": "klarge_retrieve",
        "distance_metric": "euclidean",
        "memory_concern": "retrieval",
    }
    assert tuple(composition["composition_order"]) == (
        "augmentation_memory",
        "context_memory",
    )
    assert composition["memory_aware_rope"] is True
    assert composition["memory_concern"] == "projection"


def test_flash_vstream_memory_program_has_exact_provider_operations() -> None:
    operations = flash_vstream_memory_operations()
    assert tuple(row.operation for row in operations) == (
        "flash_vstream.memory.context_compress",
        "flash_vstream.memory.augmentation_retrieve",
        "flash_vstream.memory.compose",
    )
    assert len({row.implementation_digest for row in operations}) == 3


def _egoschema_record(index: int) -> EgoSchemaTaskRecord:
    return EgoSchemaTaskRecord(
        q_uid=f"flash-{index:04d}",
        question=f"What happened in video {index}?",
        options=(
            f"option-a-{index}",
            f"option-b-{index}",
            f"option-c-{index}",
            f"option-d-{index}",
            f"option-e-{index}",
        ),
        video_content_sha256=canonical_digest({"video": index}),
        answer_index=index % 5,
    )


def test_flash_vstream_egoschema_study_binds_dual_memory_protocol() -> None:
    benchmark = build_flash_vstream_egoschema_public_cut(
        tuple(_egoschema_record(index) for index in range(EGOSCHEMA_PUBLIC_COUNT)),
        questions_content_sha256=canonical_digest({"egoschema": "questions"}),
        public_answers_content_sha256=canonical_digest({"egoschema": "answers"}),
    )
    protocol = flash_vstream_egoschema_trial_protocol(
        benchmark,
        split_id=EGOSCHEMA_PUBLIC_SPLIT,
    )
    study = build_flash_vstream_egoschema_public_study(benchmark)

    assert len(benchmark.selected_tasks(EGOSCHEMA_PUBLIC_SPLIT)) == 500
    assert protocol.protocol_id == (
        "flash-vstream.iccv2025.egoschema.public-500.v1"
    )
    assert study.trial_protocol_identity == protocol
    assert {
        row.measurement_id for row in study.measurement_protocol.definitions
    } == {
        "augmentation_memory_slot_count",
        "context_memory_slot_count",
        "multiple_choice_accuracy",
    }
    assert study.execution_policy.trial_budget.max_model_calls == 1


def test_flash_vstream_method_program_uses_one_memory_to_model_path() -> None:
    program = FLASH_VSTREAM_METHOD_PROGRAM
    assert tuple(node.node_id for node in program.graph.nodes) == (
        "compose_memory",
        "answer",
        "return",
    )
    assert program.required_runtime_ports == (MethodRuntimePort.CHILD_MACHINES,)
    assert program.required_capabilities == ("model.multimodal.generate",)
    configuration = thaw_json(program.configuration)
    assert configuration["memory_program_digest"] == (
        FLASH_VSTREAM_MEMORY_PROGRAM.program_digest
    )
    assert configuration["response_contract"] == (
        "flash-vstream.egoschema.structured-choice.v1"
    )
    assert configuration["raw_text_parser"] is None
    assert "flash-vstream.memory-child-cut" in program.evidence_obligations
    assert "multiple_choice_accuracy" in program.metric_names


def test_flash_vstream_method_program_uses_one_memory_to_model_path() -> None:
    program = FLASH_VSTREAM_METHOD_PROGRAM
    assert tuple(node.node_id for node in program.graph.nodes) == (
        "compose_memory",
        "answer",
        "return",
    )
    assert program.required_runtime_ports == (MethodRuntimePort.CHILD_MACHINES,)
    assert program.required_capabilities == ("model.multimodal.generate",)
    configuration = thaw_json(program.configuration)
    assert configuration["memory_program_digest"] == (
        FLASH_VSTREAM_MEMORY_PROGRAM.program_digest
    )
    assert configuration["response_contract"] == (
        "flash-vstream.egoschema.structured-choice.v1"
    )
    assert configuration["raw_text_parser"] is None
    assert "flash-vstream.memory-child-cut" in program.evidence_obligations
    assert "multiple_choice_accuracy" in program.metric_names
