from __future__ import annotations

import pytest

from noetrium_platform.composition.research_child_machine_batch import (
    PooledChildResearchBatchMechanics,
)
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
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
)
from noetrium_platform.research.execution.policy.api import AdmissionBudget


def _pool(*, max_children: int) -> ResearchExecutionPool:
    return ResearchExecutionPool(
        experiment_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=max_children,
            max_blocking_io_in_flight=max_children,
        ),
        experiment_admission_budget=AdmissionBudget(
            max_total_in_flight=max_children,
            max_in_flight_per_group=max_children,
            max_in_flight_per_tenant=max_children,
            max_in_flight_per_resource=max_children,
            max_blocking_io_in_flight=max_children,
        ),
    )


def _executor(*, max_children: int):
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
    pool = _pool(max_children=max_children)
    mechanics = PooledChildResearchBatchMechanics(
        single,
        execution_pool=pool,
    )
    return (
        BatchCapableRegisteredChildResearchMachineExecutor(single, mechanics),
        journal,
        pool,
    )


def _request(count: int, *, require_concurrent: bool = True):
    parent = "method:pooled-parent"
    items = tuple(
        ChildResearchMachineBatchItem(
            participant_id=f"participant-{index}",
            request=ChildResearchMachineRequest(
                host_id="fixture.concurrent-batch-child",
                parent_machine_id=parent,
                child_machine_id=f"participant:pooled:{index}",
                instance_identity={"participant": index},
                initial_data={},
                command_id_prefix=f"pooled:{index}",
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


def test_pooled_child_batch_produces_authority_bound_concurrency_evidence() -> None:
    executor, journal, pool = _executor(max_children=2)
    try:
        batch = executor.execute_batch(_request(2))

        assert batch.mode is ChildBatchExecutionMode.CONCURRENT
        assert len(batch.evidence_digests) == 1
        assert batch.receipt["worker_count"] == 2
        assert batch.receipt["atomic_ready_set"] is True
        assert (
            batch.receipt["resource_authority"]
            == "research-execution-pool/experiment"
        )
        assert len(batch.receipt["intervals"]) == 2
        assert tuple(row.child_machine_id for row in batch.links) == (
            "participant:pooled:0",
            "participant:pooled:1",
        )
        assert len(journal.commits("participant:pooled:0")) == 2
        assert len(journal.commits("participant:pooled:1")) == 2
    finally:
        pool.close()


def test_pooled_child_batch_fails_closed_without_partial_child_execution() -> None:
    executor, journal, pool = _executor(max_children=2)
    try:
        with pytest.raises(
            ValueError,
            match="batch exceeds configured capacity",
        ):
            executor.execute_batch(_request(3))

        assert journal.commits("participant:pooled:0") == ()
        assert journal.commits("participant:pooled:1") == ()
        assert journal.commits("participant:pooled:2") == ()
        assert pool.experiment_admission_snapshot().in_flight == 0
    finally:
        pool.close()


def test_concurrent_batch_identity_rejects_singleton_ready_set() -> None:
    with pytest.raises(
        ValueError,
        match="requires at least two items",
    ):
        _request(1, require_concurrent=True)
