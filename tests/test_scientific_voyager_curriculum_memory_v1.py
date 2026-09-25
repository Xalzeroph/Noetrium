from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineStatus,
    canonical_digest,
)
from research.reproductions.voyager_minecraft.curriculum_memory import (
    VoyagerQAMemoryBinding,
    VoyagerQANearestRequest,
    VoyagerQANearestResult,
    voyager_qa_memory_host,
    voyager_qa_memory_initial_data,
)


class _Nearest:
    def __init__(self, distances: dict[str, float], revision: int = 1) -> None:
        self._distances = distances
        self._revision = revision

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "nearest": "fixture",
            "revision": self._revision,
            "distances": self._distances,
        })

    def nearest(self, request: VoyagerQANearestRequest) -> VoyagerQANearestResult:
        if not request.cached_questions:
            return VoyagerQANearestResult(None, None)
        distance = self._distances.get(request.question, 1.0)
        return VoyagerQANearestResult(
            question=request.cached_questions[0],
            distance=distance,
            receipt={"query": request.question},
        )


def _event(kind: str, payload: dict) -> dict:
    return {
        "event": {
            "kind": kind,
            "payload": payload,
            "source": "test",
        }
    }


def test_voyager_qa_memory_preserves_exact_and_strict_semantic_reuse_threshold() -> None:
    journal = InMemoryMachineJournal()
    binding = VoyagerQAMemoryBinding(
        _Nearest({
            "similar question": 0.049,
            "boundary question": 0.05,
        })
    )
    host = voyager_qa_memory_host(journal=journal)
    machine_id = "memory:voyager-qa:test"
    identity = {
        "memory_id": "voyager-qa:test",
        "binding_digest": binding.binding_digest,
    }
    initial = voyager_qa_memory_initial_data()

    written = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "voyager.qa.write",
            {
                "question": "How to mine wood in Minecraft?",
                "answer": "Answer: mine a log with your hand.",
            },
        ),
        command_id_prefix="voyager-qa:test:write",
    )
    assert written.status is MachineStatus.RUNNABLE
    assert written.previous_value["entry_count"] == 1

    exact = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "voyager.qa.lookup",
            {
                "question": "How to mine wood in Minecraft?",
                "allow_semantic": False,
            },
        ),
        command_id_prefix="voyager-qa:test:exact",
    )
    assert exact.previous_value["hit"] is True
    assert exact.previous_value["match_kind"] == "exact"
    assert exact.previous_value["distance"] == 0.0

    semantic = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "voyager.qa.lookup",
            {
                "question": "similar question",
                "allow_semantic": True,
            },
        ),
        command_id_prefix="voyager-qa:test:semantic",
    )
    assert semantic.previous_value["hit"] is True
    assert semantic.previous_value["match_kind"] == "semantic"
    assert semantic.previous_value["distance"] == 0.049

    boundary = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "voyager.qa.lookup",
            {
                "question": "boundary question",
                "allow_semantic": True,
            },
        ),
        command_id_prefix="voyager-qa:test:boundary",
    )
    assert boundary.previous_value["hit"] is False
    assert boundary.previous_value["distance"] is None


def test_voyager_qa_memory_binding_identity_tracks_similarity_implementation() -> None:
    first = VoyagerQAMemoryBinding(_Nearest({}, revision=1))
    second = VoyagerQAMemoryBinding(_Nearest({}, revision=2))
    assert first.binding_digest != second.binding_digest
