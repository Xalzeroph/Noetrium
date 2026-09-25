from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    canonical_digest,
)
from noetrium_platform.research.execution.machines.api import (
    ChildFailurePolicy,
    ChildResearchHostRegistry,
    ChildResearchMachineRequest,
)
from research.reproductions.jarvis1_minecraft.fidelity import (
    JARVIS1_REFERENCE_FIDELITY,
)
from research.reproductions.jarvis1_minecraft.memory import (
    JARVIS1_MEMORY_PROGRAM,
    Jarvis1MemoryBinding,
    Jarvis1MemoryCandidate,
    Jarvis1MemoryPlanStep,
    Jarvis1MemoryRecord,
    Jarvis1MemoryRetrievalResult,
    jarvis1_memory_host,
    jarvis1_memory_initial_data,
)


def _record(task_id: str = "painting") -> Jarvis1MemoryRecord:
    return Jarvis1MemoryRecord(
        task_id=task_id,
        timestamp="2023-08-09 02:27:00",
        status="success",
        image_name="fixture.png",
        init_inventory={"iron_axe": 1},
        plan=(
            Jarvis1MemoryPlanStep(
                goal={"wool": 1},
                skill_type="mine",
                text="wool",
            ),
            Jarvis1MemoryPlanStep(
                goal={"painting": 1},
                skill_type="craft",
                text="painting",
            ),
        ),
    )


class _FixedMemory:
    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "fixture": "jarvis1-fixed-memory",
            "implementation_revision": 1,
        })

    def lookup(self, task_id: str):
        return _record(task_id) if task_id == "painting" else None


class _Retriever:
    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "fixture": "jarvis1-multimodal-retriever",
            "implementation_revision": 1,
        })

    def retrieve(self, query):
        return Jarvis1MemoryRetrievalResult(
            query_digest=query.query_digest,
            candidates=(
                Jarvis1MemoryCandidate(
                    _record("painting"),
                    0.91,
                    {"reason": "fixture"},
                ),
            ),
            retrieval_receipt={
                "visual_artifact_refs": query.visual_artifact_refs,
            },
        )


def _children(journal, *, with_retriever: bool):
    binding = Jarvis1MemoryBinding(
        _FixedMemory(),
        _Retriever() if with_retriever else None,
    )
    registry = ChildResearchHostRegistry()
    registry.register_static(
        jarvis1_memory_host(journal=journal),
        binding,
    )
    return registry.executor()


def _request(kind: str, payload: dict):
    return {
        "event": {
            "kind": kind,
            "payload": payload,
        }
    }


def test_jarvis1_public_memory_schema_preserves_partial_fixed_lane() -> None:
    fidelity = JARVIS1_REFERENCE_FIDELITY
    assert fidelity.public_offline_fixed_memory_only is True
    assert fidelity.public_memory_fields == (
        "time",
        "status",
        "image",
        "init_inventory",
        "plan",
    )
    assert fidelity.public_plan_step_fields == ("goal", "type", "text")
    assert fidelity.public_memory_state_sequence_released is False
    assert fidelity.public_memory_action_sequence_released is False
    assert fidelity.public_multimodal_descriptor_released is False
    assert fidelity.public_multimodal_retrieval_released is False
    assert fidelity.public_online_learning_released is False

    record = _record()
    assert record.source_lane == "public-fixed-memory"
    assert record.state_artifact_refs == ()
    assert record.action_artifact_refs == ()
    assert record.payload()["plan"][0]["goal"] == {"wool": 1}


def test_jarvis1_memory_machine_supports_official_exact_lookup() -> None:
    journal = InMemoryMachineJournal()
    children = _children(journal, with_retriever=False)
    execution = children.step_once(
        ChildResearchMachineRequest(
            host_id="jarvis1.multimodal-memory",
            parent_machine_id="method:jarvis1:test",
            child_machine_id="memory:jarvis1:test",
            instance_identity={
                "program_digest": JARVIS1_MEMORY_PROGRAM.program_digest,
                "lane": "public-fixed-memory",
            },
            initial_data=jarvis1_memory_initial_data(),
            failure_policy=ChildFailurePolicy.FAIL_PARENT,
            payload=_request(
                "jarvis1.memory.lookup-exact",
                {"task_id": "painting"},
            ),
            command_id_prefix="jarvis1:lookup",
        )
    )

    assert execution.status.value == "runnable"
    assert execution.result["mode"] == "official-fixed-memory"
    assert execution.result["found"] is True
    assert execution.result["record"]["task_id"] == "painting"
    assert tuple(execution.result["record"]["state_artifact_refs"]) == ()
    commits = journal.commits("memory:jarvis1:test")
    assert commits
    assert commits[-1].program_digest == JARVIS1_MEMORY_PROGRAM.program_digest


def test_jarvis1_multimodal_retrieval_is_fail_closed_without_released_policy() -> None:
    journal = InMemoryMachineJournal()
    children = _children(journal, with_retriever=False)

    with pytest.raises(
        RuntimeError,
        match="requires an explicit retriever binding",
    ):
        children.step_once(
            ChildResearchMachineRequest(
                host_id="jarvis1.multimodal-memory",
                parent_machine_id="method:jarvis1:test",
                child_machine_id="memory:jarvis1:missing-retriever",
                instance_identity={
                    "program_digest": JARVIS1_MEMORY_PROGRAM.program_digest,
                    "lane": "paper-semantic-multimodal",
                },
                initial_data=jarvis1_memory_initial_data(),
                failure_policy=ChildFailurePolicy.FAIL_PARENT,
                payload=_request(
                    "jarvis1.memory.retrieve-multimodal",
                    {
                        "instruction": "obtain painting",
                        "visual_artifact_refs": ("sha256:frame",),
                        "inventory": {"iron_axe": 1},
                    },
                ),
                command_id_prefix="jarvis1:retrieve",
            )
        )


def test_jarvis1_multimodal_retrieval_records_identity_bound_receipt() -> None:
    journal = InMemoryMachineJournal()
    children = _children(journal, with_retriever=True)
    execution = children.step_once(
        ChildResearchMachineRequest(
            host_id="jarvis1.multimodal-memory",
            parent_machine_id="method:jarvis1:test",
            child_machine_id="memory:jarvis1:retrieval",
            instance_identity={
                "program_digest": JARVIS1_MEMORY_PROGRAM.program_digest,
                "lane": "paper-semantic-multimodal",
            },
            initial_data=jarvis1_memory_initial_data(),
            failure_policy=ChildFailurePolicy.FAIL_PARENT,
            payload=_request(
                "jarvis1.memory.retrieve-multimodal",
                {
                    "instruction": "obtain painting",
                    "visual_artifact_refs": ("sha256:frame",),
                    "inventory": {"iron_axe": 1},
                },
            ),
            command_id_prefix="jarvis1:retrieve",
        )
    )

    assert execution.status.value == "runnable"
    assert execution.result["mode"] == "paper-semantic-multimodal"
    assert len(execution.result["candidates"]) == 1
    assert execution.result["candidates"][0]["score"] == 0.91
    assert execution.result["retriever_identity_digest"] == (
        _Retriever().identity_digest
    )
    assert len(execution.result["retrieval_result_digest"]) == 64
