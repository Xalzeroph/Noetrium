from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineKind,
    canonical_digest,
)
from noetrium_platform.research.execution.machines import (
    ChildResearchHostRegistry,
    ChildResearchMachineBatchItem,
    ChildResearchMachineBatchMechanicsResult,
    ChildResearchMachineBatchRequest,
    ChildResearchMachineRequest,
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


def _request(*, dispatch_parallelism: int):
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
        dispatch_parallelism=dispatch_parallelism,
    )


class _FixtureBatchMechanics:
    def __init__(self, executor, *, dispatch_parallelism: int = 2, reverse: bool = False, evidence: bool = True):
        self._executor = executor
        self._reverse = reverse
        self._dispatch_parallelism = dispatch_parallelism
        self._evidence = evidence

    @property
    def child_executor_identity_digest(self):
        return self._executor.identity_digest

    @property
    def identity_digest(self):
        return canonical_digest({
            "fixture": "concurrent-child-batch",
            "reverse": self._reverse,
            "dispatch_parallelism": self._dispatch_parallelism,
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
            dispatch_parallelism=self._dispatch_parallelism,
            executions=rows,
            evidence_digests=((
                canonical_digest({
                    "fixture": "dispatch-evidence",
                    "request_digest": request.request_digest,
                }),
            ) if self._evidence else ()),
            receipt={
                "fixture": True,
                "mechanics": "fixture-batch",
            },
        )


def test_child_batch_projection_preserves_authoritative_child_links() -> None:
    executor, journal = _registered_executor()
    request = _request(dispatch_parallelism=1)
    mechanics = _FixtureBatchMechanics(executor, dispatch_parallelism=1)
    batch = executor.execute_batch(request, mechanics)

    assert batch.dispatch_parallelism == 1
    assert tuple(row.child_machine_id for row in batch.links) == (
        "participant:batch:1",
        "participant:batch:2",
    )
    assert all(row.parent_machine_id == "method:batch-parent" for row in batch.links)
    assert batch.results == ({"done": True}, {"done": True})
    assert len(journal.commits("participant:batch:1")) == 2
    assert len(journal.commits("participant:batch:2")) == 2
    assert len(batch.execution_digest) == 64


def test_child_batch_dispatch_parallelism_drift_fails_closed() -> None:
    executor, _ = _registered_executor()
    mechanics = _FixtureBatchMechanics(executor, dispatch_parallelism=1)
    with pytest.raises(ValueError, match="dispatch_parallelism drifted"):
        executor.execute_batch(_request(dispatch_parallelism=2), mechanics)


def test_parallel_child_batch_requires_dispatch_evidence() -> None:
    executor, _ = _registered_executor()
    mechanics = _FixtureBatchMechanics(
        executor, dispatch_parallelism=2, evidence=False
    )
    with pytest.raises(ValueError, match="requires dispatch evidence"):
        executor.execute_batch(_request(dispatch_parallelism=2), mechanics)


def test_child_batch_requires_dispatch_evidence_and_exact_order() -> None:
    executor, _ = _registered_executor()
    request = _request(dispatch_parallelism=2)

    success = executor.execute_batch(
        request,
        _FixtureBatchMechanics(executor),
    )
    assert success.dispatch_parallelism == 2
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
        dispatch_parallelism=2,
    )
    with pytest.raises(
        ValueError,
        match="order/child identity mismatch",
    ):
        executor.execute_batch(
            wrong_order_request,
            _FixtureBatchMechanics(executor, reverse=True),
        )


def test_single_child_executor_exposes_batch_capability() -> None:
    executor, _ = _registered_executor()
    mechanics = _FixtureBatchMechanics(executor)
    batch = executor.execute_batch(
        _request(dispatch_parallelism=2),
        mechanics,
    )

    assert batch.dispatch_parallelism == 2
    assert len(executor.identity_digest) == 64
    single = executor.execute(
        ChildResearchMachineRequest(
            host_id="fixture.batch-child",
            parent_machine_id="method:single-parent",
            child_machine_id="participant:single:1",
            instance_identity={"participant": "single"},
            initial_data={},
        )
    )
    assert single.result == {"done": True}
