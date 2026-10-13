from __future__ import annotations

from resource_test_support import make_execution_pool

import pytest

from noetrium_platform.composition.unit_activation_pool import (
    PooledUnitActivationMechanics,
)
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.research.execution.policy.api import ExecutionBudgetPolicy
from noetrium_platform.research.execution.policy.runtime import SQLiteExecutionBudgetAuthority
from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.kernel.unit_activation import (
    UnitActivationRegistry,
    UnitActivationRequest,
)
from noetrium_platform.foundation.kernel.kernel.unit_activation_batch import (
    UnitActivationBatchItem,
    UnitActivationBatchRequest,
)
from noetrium_platform.foundation.kernel.kernel.unit_host import BoundExecutableUnit, UnitOperationBinding
from noetrium_platform.foundation.kernel.kernel.universal import (
    executable_unit,
    unit_operation,
    UnitTransition,
)
from noetrium_platform.research.execution.policy.api import (
    AdmissionBudget,
    AdmissionRejected,
)


class _ScientificControl:
    def __init__(self, budget, scope_id: str) -> None:
        self._budget = budget
        self._scope_id = scope_id

    @property
    def cancelled(self) -> bool:
        return False

    @property
    def reason(self):
        return None

    @property
    def deadline(self):
        return None

    @property
    def remaining_seconds(self):
        return None

    @property
    def scientific_time_active(self) -> bool:
        return self._budget.snapshot(self._scope_id).scientific_time_active

    @property
    def scientific_deadline(self):
        return None

    def activate_scientific_time(self) -> None:
        self._budget.activate_scope(self._scope_id)

    def wait(self, timeout=None) -> bool:
        return False

    def checkpoint(self) -> None:
        return None

    def subscribe_cancel(self, callback):
        return lambda: None


def _pool(*, max_children: int) -> ResearchExecutionPool:
    return make_execution_pool(
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
        machine_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=max_children,
            max_blocking_io_in_flight=max_children,
        ),
        machine_admission_budget=AdmissionBudget(
            max_total_in_flight=max_children,
            max_in_flight_per_group=max_children,
            max_in_flight_per_tenant=max_children,
            max_in_flight_per_resource=max_children,
            max_blocking_io_in_flight=max_children,
        ),
    )


def _executor(*, max_children: int, tmp_path):
    journal = InMemoryMachineJournal()
    program = executable_unit(
        "fixture.concurrent-batch-child",
        domain="participant",
        version="1",
        state_schema="fixture.concurrent-batch-child.state.v1",
        entrypoint="return",
        members=(unit_operation(
            "return", "fixture.return", configuration={"value": {"done": True}},
        ),),
    )
    host = BoundExecutableUnit(
        host_id="fixture.concurrent-batch-child",
        unit=program,
        operations=(
            UnitOperationBinding(
                "fixture.return",
                lambda request, binding: UnitTransition.halt(value={"done": True}),
                canonical_digest({"fixture": "unit-batch-return", "version": 1}),
            ),
        ),
        journal=journal,
        max_steps=4,
    )
    registry = UnitActivationRegistry()
    registry.register_static(host)
    single = registry.runtime()
    pool = _pool(max_children=max_children)
    budget = SQLiteExecutionBudgetAuthority(
        tmp_path / ("budget-" + str(max_children) + ".sqlite"),
        resource_policy_digest="a" * 64,
        checkpoint_replay_proof_digest="b" * 64,
    )
    scope_id = "assignment-pooled"
    budget.open_scope(
        ExecutionBudgetPolicy(
            scope_id=scope_id,
            budget_id="pooled-test",
            budget_digest=canonical_digest({"budget": "pooled-test"}),
            replay_level="observational",
            max_seconds=30.0,
        )
    )
    control = _ScientificControl(budget, scope_id)
    mechanics = PooledUnitActivationMechanics(
        single,
        execution_pool=pool,
        parent_control=control,
    )
    return (
        single,
        mechanics,
        journal,
        pool,
        budget,
        control,
    )


def _request(count: int):
    parent = "method:pooled-parent"
    items = tuple(
        UnitActivationBatchItem(
            participant_id=f"participant-{index}",
            request=UnitActivationRequest(
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
    return UnitActivationBatchRequest(
        batch_id=f"ready-set:{count}",
        parent_machine_id=parent,
        selection_digest=canonical_digest({
            "ready_set": tuple(row.participant_id for row in items),
        }),
        items=items,
    )


def test_pooled_child_batch_produces_authority_bound_concurrency_evidence(tmp_path) -> None:
    executor, mechanics, journal, pool, budget, control = _executor(max_children=2, tmp_path=tmp_path)
    try:
        assert not budget.snapshot("assignment-pooled").scientific_time_active
        assert not control.scientific_time_active
        batch = executor.execute_batch(_request(2), mechanics)

        assert budget.snapshot("assignment-pooled").scientific_time_active
        assert control.scientific_time_active
        assert len(batch.evidence_digests) == 1
        assert batch.receipt["dispatch_strategy"] == "authority-maximal-ready-prefix"
        assert (
            batch.receipt["resource_authority"]
            == "research-execution-pool/unit"
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
        budget.close()


def test_pooled_child_batch_preserves_existing_scientific_clock(tmp_path) -> None:
    executor, mechanics, journal, pool, budget, control = _executor(max_children=2, tmp_path=tmp_path)
    try:
        control.activate_scientific_time()
        started = budget.snapshot("assignment-pooled").started_unix_ns
        assert started > 0
        batch = executor.execute_batch(_request(2), mechanics)
        assert len(batch.executions) == 2
        assert budget.snapshot("assignment-pooled").started_unix_ns == started
    finally:
        pool.close()
        budget.close()


def test_pooled_child_batch_adapts_ready_set_to_authority_capacity(tmp_path) -> None:
    executor, mechanics, journal, pool, budget, control = _executor(max_children=2, tmp_path=tmp_path)
    try:
        batch = executor.execute_batch(_request(3), mechanics)
        assert len(batch.executions) == 3
        assert batch.receipt["initial_batch_size"] == 2
        assert batch.receipt["refill_count"] == 1
        assert pool.machine_admission_snapshot().in_flight == 0
    finally:
        pool.close()
        budget.close()

def test_pooled_child_batch_runs_larger_ready_set_in_bounded_rolling_window(tmp_path) -> None:
    executor, mechanics, journal, pool, budget, control = _executor(max_children=2, tmp_path=tmp_path)
    try:
        batch = executor.execute_batch(_request(4), mechanics)
        assert batch.receipt["initial_batch_size"] == 2
        assert batch.receipt["refill_count"] == 2
        assert len(batch.executions) == 4
        assert all(len(journal.commits(f"participant:pooled:{index}")) == 2 for index in range(4))
    finally:
        pool.close()
        budget.close()


def test_wide_unit_ready_set_materializes_only_admissible_prefixes(
    tmp_path, monkeypatch,
) -> None:
    """An N-wide DAG frontier must not rebuild its N-node tail per completion.

    Each actual child remains an independently journaled Unit activation; the
    pool alone owns capacity and the read-only admission snapshot is advisory.
    """
    count = 24
    executor, mechanics, journal, pool, budget, control = _executor(
        max_children=2, tmp_path=tmp_path,
    )
    generated: list[int] = []
    snapshots = []
    original = mechanics._task_id
    original_snapshot = pool.machine_admission_snapshot

    def snapshot_once():
        snapshots.append(True)
        return original_snapshot()

    monkeypatch.setattr(pool, "machine_admission_snapshot", snapshot_once)

    def spy_task_id(index, item):
        generated.append(index)
        return original(index, item)

    monkeypatch.setattr(mechanics, "_task_id", spy_task_id)
    try:
        batch = executor.execute_batch(_request(count), mechanics)
        assert len(batch.links) == count
        assert tuple(link.child_machine_id for link in batch.links) == tuple(
            f"participant:pooled:{index}" for index in range(count)
        )
        # A candidate is created exactly once even if a provider temporarily
        # denies admission, instead of rebuilding the remaining ready-set tail.
        assert sorted(generated) == list(range(count))
        assert batch.receipt["constructed_candidates"] == count
        assert snapshots == [True]
        assert batch.receipt["peak_pending_candidates"] <= 2
        assert batch.receipt["peak_submitted_handles"] <= 2
        assert batch.receipt["candidate_projection"] == (
            "capacity-window-single-materialization.v1"
        )
        assert all(len(journal.commits(f"participant:pooled:{index}")) == 2
                   for index in range(count))
        assert pool.machine_admission_snapshot().in_flight == 0
        assert control.scientific_time_active
    finally:
        pool.close()
        budget.close()


def test_unit_async_pipeline_reuses_pending_candidate_after_transient_denial(
    tmp_path, monkeypatch,
) -> None:
    """Temporary physical-capacity denial never invents a second Unit intent."""
    executor, mechanics, journal, pool, budget, _control = _executor(
        max_children=2, tmp_path=tmp_path,
    )
    original_open = pool.open_machine_group
    denied = []
    generated = []
    original_task_id = mechanics._task_id

    def open_with_one_denial(*args, **kwargs):
        group = original_open(*args, **kwargs)
        original_try = group.try_submit_maximal_batch

        def try_with_denial(items, *, deadline=None):
            if not denied:
                denied.append(True)
                return ()
            return original_try(items, deadline=deadline)

        monkeypatch.setattr(group, "try_submit_maximal_batch", try_with_denial)
        return group

    def spy_task_id(index, item):
        generated.append(index)
        return original_task_id(index, item)

    monkeypatch.setattr(pool, "open_machine_group", open_with_one_denial)
    monkeypatch.setattr(mechanics, "_task_id", spy_task_id)
    try:
        count = 12
        batch = executor.execute_batch(_request(count), mechanics)
        assert len(batch.links) == count
        assert denied == [True]
        assert sorted(generated) == list(range(count))
        assert batch.receipt["constructed_candidates"] == count
        assert batch.receipt["peak_pending_candidates"] <= 2
        assert batch.receipt["peak_submitted_handles"] <= 2
        assert batch.receipt["candidate_projection"] == (
            "capacity-window-single-materialization.v1"
        )
        assert all(len(journal.commits(f"participant:pooled:{index}")) == 2
                   for index in range(count))
        assert pool.machine_admission_snapshot().in_flight == 0
    finally:
        pool.close()
        budget.close()



def test_scientific_clock_barrier_is_singleflight_at_first_worker_entry(
    tmp_path, monkeypatch,
) -> None:
    """N concurrent children must not trigger N SQLite scope-probe writes."""
    executor, mechanics, journal, pool, budget, control = _executor(
        max_children=4, tmp_path=tmp_path,
    )
    original_get = _ScientificControl.scientific_time_active.fget
    original_activate = control.activate_scientific_time
    probes: list[bool] = []
    activations: list[bool] = []

    def observed_clock(self):
        probes.append(True)
        return original_get(self)

    def activate():
        activations.append(True)
        original_activate()

    monkeypatch.setattr(
        _ScientificControl, "scientific_time_active", property(observed_clock),
    )
    monkeypatch.setattr(control, "activate_scientific_time", activate)
    try:
        batch = executor.execute_batch(_request(24), mechanics)
        assert len(batch.links) == 24
        assert probes == [True]
        assert activations == [True]
        assert budget.snapshot("assignment-pooled").scientific_time_active
        assert all(len(journal.commits(f"participant:pooled:{index}")) == 2
                   for index in range(24))
    finally:
        pool.close()
        budget.close()



def test_single_unit_activation_starts_without_global_admission_snapshot(
    tmp_path, monkeypatch,
) -> None:
    executor, mechanics, journal, pool, budget, _control = _executor(
        max_children=2, tmp_path=tmp_path,
    )
    def forbidden_snapshot():
        raise AssertionError(
            "a single Unit must not block on global topology projection"
        )
    monkeypatch.setattr(
        pool, "machine_admission_snapshot", forbidden_snapshot,
    )
    try:
        batch = executor.execute_batch(_request(1), mechanics)
        assert len(batch.links) == 1
        assert batch.receipt["constructed_candidates"] == 1
        assert batch.receipt["nonblocking_admission_calls"] == 0
        assert len(journal.commits("participant:pooled:0")) == 2
    finally:
        pool.close()
        budget.close()
