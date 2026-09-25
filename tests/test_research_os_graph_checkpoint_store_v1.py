from __future__ import annotations

import json

import pytest

from noetrium_platform.composition.research_os_checkpoint import (
    ResearchOSGraphCheckpoint,
    ResearchOSGraphCheckpointCorruptionError,
)
from noetrium_platform.composition.research_os_checkpoint_store import (
    DirectoryResearchOSGraphCheckpointStore,
)


def _checkpoint(
    *,
    snapshot_generation: int = 1,
    control_generation: int = 1,
    state: str = "succeeded",
) -> ResearchOSGraphCheckpoint:
    return ResearchOSGraphCheckpoint(
        execution_cut_id="a" * 64,
        graph_digest="b" * 64,
        research_revision_digest="c" * 64,
        snapshot_generation=snapshot_generation,
        control_generation=control_generation,
        control_phase="paused",
        selected_node_ids=("paper::node",),
        nodes=(
            {
                "graph_node_id": "paper::node",
                "semantic_digest": "d" * 64,
                "state": state,
                "attempt_number": 1,
                "authority_id": "machine-journal",
                "checkpoint_proof_digest": "e" * 64,
            },
        ),
    )


def test_graph_checkpoint_survives_store_restart_and_scope_lookup(tmp_path) -> None:
    root = tmp_path / "graph-checkpoints"
    first = DirectoryResearchOSGraphCheckpointStore(root)
    checkpoint = _checkpoint()
    assert first.publish(checkpoint) == checkpoint

    restarted = DirectoryResearchOSGraphCheckpointStore(root)
    assert restarted.load(checkpoint.checkpoint_digest) == checkpoint
    assert restarted.latest(
        checkpoint.execution_cut_id,
        checkpoint.selected_node_ids,
    ) == checkpoint


def test_graph_checkpoint_store_rejects_corrupt_content_addressed_object(tmp_path) -> None:
    root = tmp_path / "graph-checkpoints"
    store = DirectoryResearchOSGraphCheckpointStore(root)
    checkpoint = _checkpoint()
    store.publish(checkpoint)

    object_path = root / "objects" / f"{checkpoint.checkpoint_digest}.json"
    document = json.loads(object_path.read_text(encoding="utf-8"))
    document["control_phase"] = "active"
    object_path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    restarted = DirectoryResearchOSGraphCheckpointStore(root)
    with pytest.raises(ResearchOSGraphCheckpointCorruptionError):
        restarted.load(checkpoint.checkpoint_digest)


def test_graph_checkpoint_latest_is_monotonic_and_conflict_safe(tmp_path) -> None:
    store = DirectoryResearchOSGraphCheckpointStore(tmp_path / "graph-checkpoints")
    current = _checkpoint(snapshot_generation=3, control_generation=4)
    store.publish(current)

    with pytest.raises(ValueError, match="snapshot generation moved backwards"):
        store.publish(_checkpoint(snapshot_generation=2, control_generation=4))

    with pytest.raises(ValueError, match="control generation moved backwards"):
        store.publish(_checkpoint(snapshot_generation=4, control_generation=3))

    with pytest.raises(ValueError, match="conflicting content"):
        store.publish(
            _checkpoint(
                snapshot_generation=3,
                control_generation=4,
                state="reused",
            )
        )

    assert store.latest(
        current.execution_cut_id,
        current.selected_node_ids,
    ) == current
