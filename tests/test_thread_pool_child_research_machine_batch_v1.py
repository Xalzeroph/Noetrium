from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineKind,
    canonical_digest,
)
from noetrium_platform.research.execution.machines import (
    BatchCapableRegisteredChildResearchMachineExecutor,
    ChildBatchExecutionMode,
    ChildResearchHostRegistry,
    ChildResearchMachineBatchItem,
    ChildResearchMachineBatchRequest,
    ChildResearchMachineRequest,
    ResearchProgramBuilder,
    ResearchProgramHost,
    ThreadPoolChildResearchBatchMechanics,
)


def _executor(*, max_workers: int):
    journal = InMemoryMachineJournal()
    program = (
        ResearchProgramBuilder(
            program_id="fixture.concurrent-batch-child",
            kind=MachineKind.PARTICIPANT,
            version="1",
            state_schema="fixture.concurrent-batch-child.state.v1",
            entrypoint="return",
        )
        .node(
            "return",
            "core.return",
            configuration={"value": {"done": True}},
        )
        .build()
    )
    host = ResearchProgramHost(
        host_id="fixture.concurrent-batch-child",
        program=program,
        operations=(),
        journal=journal,
        max_steps=4,
    )
    registry = ChildResearchHostRegistry()
    registry.register_static(host)
    single = registry.executor()
    mechanics = ThreadPoolChildResearchBatchMechanics(
        single,
        max_workers=max_workers,
    )
    return (
        BatchCapableRegisteredChildResearchMachineExecutor(single, mechanics),
        journal,
    )


def _request(count: int, *, require_concurrent: bool = True):
    parent = "method:thread-pool-parent"
    items = tuple(
        ChildResearchMachineBatchItem(
            participant_id=f"participant-{index}",
            request=ChildResearchMachineRequest(
                host_id="fixture.concurrent-batch-child",
                parent_machine_id=parent,
                child_machine_id=f"participant:thread-pool:{index}",
                instance_identity={"participant": index},
                initial_data={},
                command_id_prefix=f"thread-pool:{index}",
            ),
        )
        for index in range(count)
    )
    return ChildResearchMachineBatchRequest(
        batch_id=f"ready-set:{count}",
        parent_machine_id=parent,
        selection_digest=canonical_digest({
            "ready_set": tuple(row.participant_id for row in items),
        }),
        items=items,
        require_concurrent=require_concurrent,
    )


def test_thread_pool_child_batch_produces_concurrency_evidence() -> None:
    executor, journal = _executor(max_workers=2)
    batch = executor.execute_batch(_request(2))

    assert batch.mode is ChildBatchExecutionMode.CONCURRENT
    assert len(batch.evidence_digests) == 1
    assert batch.receipt["worker_count"] == 2
    assert batch.receipt["full_ready_set_synchronized"] is True
    assert len(batch.receipt["intervals"]) == 2
    assert tuple(row.child_machine_id for row in batch.links) == (
        "participant:thread-pool:0",
        "participant:thread-pool:1",
    )
    assert len(journal.commits("participant:thread-pool:0")) == 2
    assert len(journal.commits("participant:thread-pool:1")) == 2


def test_thread_pool_child_batch_fails_closed_when_ready_set_exceeds_capacity() -> None:
    executor, journal = _executor(max_workers=2)

    with pytest.raises(
        ValueError,
        match="ready set exceeds thread-pool worker capacity",
    ):
        executor.execute_batch(_request(3))

    assert journal.commits("participant:thread-pool:0") == ()
    assert journal.commits("participant:thread-pool:1") == ()
    assert journal.commits("participant:thread-pool:2") == ()
