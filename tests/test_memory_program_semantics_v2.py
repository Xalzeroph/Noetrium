
from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    InMemoryMachineJournal,
)
from noetrium_platform.research.execution.machines import (
    ChildResearchHostRegistry,
    ChildResearchMachineRequest,
    MachineEvent,
    MemoryConcern,
    MemoryRecord,
    default_memory_host,
    memory_initial_data,
)
from noetrium_platform.research.execution.method import (
    MemoryScope,
    ResearchMethodCall,
)
from noetrium_platform.research.execution.workflow.api import MethodNodeRequest


class _ChildRuntime:
    identity_digest = "a" * 64

    def execute(self, request):
        raise AssertionError("not used")

    def step_once(self, request):
        raise AssertionError("not used")


def _call(
    *,
    run_id: str = "run-a",
    task_id: str | None = "task-a",
) -> ResearchMethodCall:
    context = ExecutionContext(
        run_id,
        "trace-a",
        "span-a",
        study_id="study-a",
        condition_id="condition-a",
        assignment_seed="seed-a",
        repetition=2,
        lifetime_id="lifetime-a",
        branch_id="branch-a",
        task_id=task_id,
        decision_cycle_id="cycle-a",
        checkpoint_id="checkpoint-a",
        operation_id="operation-a",
        component_id="component-a",
        execution_tenant_id="tenant-a",
        participant_context={"role": "planner"},
    )
    return ResearchMethodCall._from_internal(
        MethodNodeRequest(
            "node-a",
            0,
            {},
            None,
            context,
            child_machines=_ChildRuntime(),
            parent_machine_id="method:parent-a",
        )
    )


def test_method_call_projects_memory_relevant_execution_identity() -> None:
    call = _call()
    assert call.study_id == "study-a"
    assert call.repetition == 2
    assert call.task_id == "task-a"
    assert call.decision_cycle_id == "cycle-a"
    assert call.branch_id == "branch-a"
    assert call.checkpoint_id == "checkpoint-a"
    assert call.operation_id == "operation-a"
    assert call.component_id == "component-a"
    assert call.execution_tenant_id == "tenant-a"
    assert call.parent_machine_id == "method:parent-a"


def test_memory_scope_identity_is_stable_and_scope_sensitive() -> None:
    first = _call(run_id="run-a", task_id="task-a")
    second = _call(run_id="run-b", task_id="task-a")

    first_task_id, first_task_identity = first.memory_component_identity(
        host_id="episodic.memory",
        memory_id="experience",
        scope=MemoryScope.TASK,
    )
    second_task_id, second_task_identity = second.memory_component_identity(
        host_id="episodic.memory",
        memory_id="experience",
        scope=MemoryScope.TASK,
    )
    assert first_task_id == second_task_id
    assert first_task_identity == second_task_identity

    first_run_id, _ = first.memory_component_identity(
        host_id="episodic.memory",
        memory_id="experience",
        scope=MemoryScope.RUN,
    )
    second_run_id, _ = second.memory_component_identity(
        host_id="episodic.memory",
        memory_id="experience",
        scope=MemoryScope.RUN,
    )
    assert first_run_id != second_run_id

    participant_id, participant_identity = first.memory_component_identity(
        host_id="episodic.memory",
        memory_id="experience",
        scope=MemoryScope.PARTICIPANT,
        scope_key={"participant_id": "agent-7"},
    )
    assert participant_id.startswith("memory:experience:")
    assert participant_identity["scope"]["scope"] == "participant"
    assert participant_identity["scope"]["scope_key"] == {
        "participant_id": "agent-7"
    }

    with pytest.raises(ValueError, match="participant"):
        first.memory_component_identity(
            host_id="episodic.memory",
            memory_id="experience",
            scope=MemoryScope.PARTICIPANT,
        )


def _step(session, event_type: str, payload: dict[str, object], command: str) -> None:
    session.step(
        {
            "event": MachineEvent(
                event_type,
                payload,
                source="test",
            ).as_payload()
        },
        command_id=command,
    )


def test_default_memory_supports_rewrite_and_candidate_level_retrieval() -> None:
    journal = InMemoryMachineJournal()
    host = default_memory_host(journal=journal)
    session = host.open_session(
        machine_id="memory:test",
        instance_identity={"memory_id": "test"},
        binding=None,
    )
    session.start(memory_initial_data(), command_id="memory:test:start")

    first = MemoryRecord(
        record_id="fact:a",
        kind="fact",
        content="alice works on memory systems",
        generation="world-1",
        state_digest="1" * 64,
        tags=("alice", "memory"),
        verified=True,
        metadata={"scope": "task-a", "entity": "alice"},
    )
    second = MemoryRecord(
        record_id="fact:b",
        kind="fact",
        content="bob works on web agents",
        generation="world-1",
        state_digest="2" * 64,
        tags=("bob", "web"),
        verified=True,
        metadata={"scope": "task-b", "entity": "bob"},
    )
    _step(session, "memory.write", {"record": first.as_payload()}, "write:a")
    _step(session, "memory.write", {"record": second.as_payload()}, "write:b")

    _step(
        session,
        "memory.update",
        {
            "record_id": "fact:a",
            "patch": {
                "content": "alice builds adaptive agent memory systems",
                "metadata": {
                    "scope": "task-a",
                    "entity": "alice",
                    "version": 2,
                },
            },
        },
        "update:a",
    )
    update_result = session.previous_value
    assert update_result["record_id"] == "fact:a"
    assert update_result["before_record_digest"] != update_result["record_digest"]

    _step(
        session,
        "memory.retrieve",
        {
            "query_text": "alice memory",
            "kinds": ("fact",),
            "metadata_filter": {"scope": "task-a"},
            "include_records": True,
            "min_score": 1,
            "limit": 8,
        },
        "retrieve:a",
    )
    value = session.previous_value
    assert value["record_ids"] == ("fact:a",)
    assert value["records"][0]["content"] == (
        "alice builds adaptive agent memory systems"
    )
    assert value["records"][0]["metadata"]["version"] == 2

    _step(
        session,
        "memory.retrieve",
        {
            "query_text": "alice memory",
            "metadata_filter": {"scope": "task-a"},
            "exclude_record_ids": ("fact:a",),
            "include_records": True,
            "limit": 8,
        },
        "retrieve:excluded",
    )
    assert session.previous_value["record_ids"] == ()


def test_memory_concern_vocabulary_covers_modern_memory_lifecycle() -> None:
    required = {
        "encoding",
        "write",
        "update",
        "association",
        "index",
        "retrieval",
        "reranking",
        "access",
        "trust",
        "consolidation",
        "decay",
        "retention",
        "projection",
        "scope",
        "migration",
        "reconciliation",
        "recovery",
    }
    assert required <= {item.value for item in MemoryConcern}



def test_scoped_memory_reopens_across_different_parent_method_machines() -> None:
    journal = InMemoryMachineJournal()
    host = default_memory_host(journal=journal)
    registry = ChildResearchHostRegistry()
    registry.register_static(host, None)
    executor = registry.executor()

    child_id = "memory:shared-study"
    identity = {
        "schema": "noetrium.method-memory-scope.v1",
        "scope": "study",
        "scope_key": "study-a",
    }
    initial = memory_initial_data()
    record = MemoryRecord(
        record_id="fact:shared",
        kind="fact",
        content="shared memory survives a parent Method boundary",
        generation="world-1",
        state_digest="3" * 64,
        tags=("shared", "memory"),
        verified=True,
    )
    written = executor.step_once(
        ChildResearchMachineRequest(
            host_id="memory.default",
            parent_machine_id="method:episode-a",
            child_machine_id=child_id,
            instance_identity=identity,
            initial_data=initial,
            payload={
                "event": MachineEvent(
                    "memory.write",
                    {"record": record.as_payload()},
                    source="test",
                ).as_payload()
            },
            command_id_prefix="episode-a",
        )
    )
    assert written.link.parent_machine_id == "method:episode-a"

    recalled = executor.step_once(
        ChildResearchMachineRequest(
            host_id="memory.default",
            parent_machine_id="method:episode-b",
            child_machine_id=child_id,
            instance_identity=identity,
            initial_data=initial,
            payload={
                "event": MachineEvent(
                    "memory.retrieve",
                    {
                        "query_text": "shared memory",
                        "require_verified": True,
                        "include_records": True,
                    },
                    source="test",
                ).as_payload()
            },
            command_id_prefix="episode-b",
        )
    )
    assert recalled.link.parent_machine_id == "method:episode-b"
    assert recalled.result["record_ids"] == ("fact:shared",)
    assert recalled.result["records"][0]["content"] == record.content
