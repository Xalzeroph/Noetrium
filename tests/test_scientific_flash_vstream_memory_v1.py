from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import MachineKind, thaw_json
from research.reproductions.flash_vstream_memory.fidelity import (
    FLASH_VSTREAM_REFERENCE_FIDELITY,
)
from research.reproductions.flash_vstream_memory.memory import (
    FLASH_VSTREAM_MEMORY_PROGRAM,
    flash_vstream_memory_operations,
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
    assert composition == {
        "composition_order": (
            "augmentation_memory",
            "context_memory",
        ),
        "memory_aware_rope": True,
        "memory_concern": "projection",
    }


def test_flash_vstream_memory_program_has_exact_provider_operations() -> None:
    operations = flash_vstream_memory_operations()
    assert tuple(row.operation for row in operations) == (
        "flash_vstream.memory.context_compress",
        "flash_vstream.memory.augmentation_retrieve",
        "flash_vstream.memory.compose",
    )
    assert len({row.implementation_digest for row in operations}) == 3
