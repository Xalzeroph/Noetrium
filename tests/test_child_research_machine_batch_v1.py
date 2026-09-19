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
    ChildResearchMachineBatchExecutor,
    ChildResearchMachineBatchItem,
    ChildResearchMachineBatchMechanicsResult,
    ChildResearchMachineBatchRequest,
    ChildResearchMachineRequest,
    RegisteredSerialChildResearchBatchMechanics,
    ResearchProgramBuilder,
    ResearchProgramHost,
)


def _registered_executor():
    journal = InMemoryMachineJournal()
    program = (
        ResearchProgramBuilder(
            program_id="fixture.batch-child",
            kind=MachineKind.PARTICIPANT,
            version="1",
            state_schema="fixture.batch-child.state.v1",
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
        host_id="fixture.batch-child",
        program=program,
        operations=(),
        journal=journal,
        max_steps=4,
    )
    registry = ChildResearchHostRegistry()
    registry.register_static(host)
    return registry.executor(), journal


def _request(*, require_concurrent: bool):
    parent = "method:batch-parent"
    items = tuple(
        ChildResearchMachineBatchItem(
            participant_id=f"participant-{index}",
            request=ChildResearchMachineRequest(
                host_id="fixture.batch-child",
                parent_machine_id=parent,
                child_machine_id=f"participant:batch:{index}",
                instance_identity={"participant": index},
                initial_data={},
                command_id_prefix=f"batch:{index}",
            ),
        )
        for index in (1, 2)
    )
    return ChildResearchMachineBatchRequest(
        batch_id="ready-set:1",
        parent_machine_id=parent,
        selection_digest=canonical_digest({
            "decision": "ready-set:1",
            "participants": tuple(row.participant_id for row in items),
        }),
        items=items,
        require_concurrent=require_concurrent,
    )


class _FixtureConcurrentMechanics:
    def __init__(self, executor, *, reverse: bool = False):
        self._executor = executor
        self._reverse = reverse

    @property
    def identity_digest(self):
        return canonical_digest({
            "fixture": "concurrent-child-batch",
            "reverse": self._reverse,
        })

    def execute_batch(self, request):
        rows = tuple(
            self._executor.execute(item.request)
            for item in request.items
        )
        if self._reverse:
            rows = tuple(reversed(rows))
        return ChildResearchMachineBatchMechanicsResult(
            request_digest=request.request_digest,
            mode=ChildBatchExecutionMode.CONCURRENT,
            executions=rows,
            evidence_digests=(
                canonical_digest({
                    "fixture": "concurrency-evidence",
                    "request_digest": request.request_digest,
                }),
            ),
            receipt={
                "fixture": True,
                "mechanics": "concurrent",
            },
        )


def test_child_batch_serial_projection_preserves_authoritative_child_links() -> None:
    executor, journal = _registered_executor()
    request = _request(require_concurrent=False)
    batch = ChildResearchMachineBatchExecutor(
        RegisteredSerialChildResearchBatchMechanics(executor)
    ).execute(request)

    assert batch.mode is ChildBatchExecutionMode.SERIAL
    assert tuple(row.child_machine_id for row in batch.links) == (
        "participant:batch:1",
        "participant:batch:2",
    )
    assert all(
        row.parent_machine_id == "method:batch-parent"
        for row in batch.links
    )
    assert batch.results == ({"done": True}, {"done": True})
    assert len(journal.commits("participant:batch:1")) == 2
    assert len(journal.commits("participant:batch:2")) == 2
    assert len(batch.execution_digest) == 64


def test_child_batch_concurrency_requirement_fails_closed_on_serial_mechanics() -> None:
    executor, _ = _registered_executor()
    batch = ChildResearchMachineBatchExecutor(
        RegisteredSerialChildResearchBatchMechanics(executor)
    )

    with pytest.raises(
        ValueError,
        match="requires concurrent mechanics",
    ):
        batch.execute(_request(require_concurrent=True))


def test_child_batch_requires_concurrency_evidence_and_exact_order() -> None:
    executor, _ = _registered_executor()
    request = _request(require_concurrent=True)

    success = ChildResearchMachineBatchExecutor(
        _FixtureConcurrentMechanics(executor)
    ).execute(request)
    assert success.mode is ChildBatchExecutionMode.CONCURRENT
    assert len(success.evidence_digests) == 1
    assert tuple(row.child_machine_id for row in success.links) == (
        "participant:batch:1",
        "participant:batch:2",
    )

    wrong_order_request = ChildResearchMachineBatchRequest(
        batch_id="ready-set:2",
        parent_machine_id="method:batch-parent",
        selection_digest=canonical_digest({"decision": "ready-set:2"}),
        items=tuple(
            ChildResearchMachineBatchItem(
                participant_id=f"other-{index}",
                request=ChildResearchMachineRequest(
                    host_id="fixture.batch-child",
                    parent_machine_id="method:batch-parent",
                    child_machine_id=f"participant:other:{index}",
                    instance_identity={"participant": index},
                    initial_data={},
                ),
            )
            for index in (1, 2)
        ),
        require_concurrent=True,
    )
    with pytest.raises(
        ValueError,
        match="order/child identity mismatch",
    ):
        ChildResearchMachineBatchExecutor(
            _FixtureConcurrentMechanics(executor, reverse=True)
        ).execute(wrong_order_request)


def test_batch_capable_wrapper_keeps_single_child_abi_and_adds_batch_capability() -> None:
    executor, _ = _registered_executor()
    wrapper = BatchCapableRegisteredChildResearchMachineExecutor(
        executor,
        _FixtureConcurrentMechanics(executor),
    )
    batch = wrapper.execute_batch(_request(require_concurrent=True))

    assert batch.mode is ChildBatchExecutionMode.CONCURRENT
    assert len(wrapper.identity_digest) == 64
    single = wrapper.execute(
        ChildResearchMachineRequest(
            host_id="fixture.batch-child",
            parent_machine_id="method:single-parent",
            child_machine_id="participant:single:1",
            instance_identity={"participant": "single"},
            initial_data={},
        )
    )
    assert single.result == {"done": True}
