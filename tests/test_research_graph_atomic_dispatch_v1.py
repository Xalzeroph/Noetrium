"""The unified event-driven scheduling path, authority cuts and recovery."""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

from noetrium_platform.composition.research_graph_dispatch_index import ResearchGraphDispatchIndex
from noetrium_platform.composition.research_graph_frontier import ResearchGraphDependencyFrontier
from noetrium_platform.foundation.kernel.concurrency.scheduling.api import (
    ExecutionPriority, SchedulingCandidate,
)
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
    DurableUnifiedSchedulingAuthority, UnifiedSchedulingAuthority,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    execution_flow, execution_graph, execution_vertex,
    ResearchGraphNodeResult, ResearchGraphNodeState,
)


def _candidate(index, *, tenant="same", flow=None, deadline=None, service=None):
    return SchedulingCandidate(
        ticket=index, group_id=flow or f"flow-{index}",
        tenant_id=tenant, priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=1.0, deterministic_tiebreak=index,
        estimated_service_cost=float(index),
        flow_id=flow, deadline_monotonic=deadline,
        estimated_service_seconds=service,
    )


def _oracle(authority, candidates, *, now):
    return tuple(
        sorted(candidates, key=lambda x: authority.ordering_key(x, now_monotonic=now))
    )


def test_grouped_incremental_dispatch_equals_single_authoritative_sort():
    authority = UnifiedSchedulingAuthority()
    values = {f"u{i}": _candidate(i) for i in range(200)}
    index = ResearchGraphDispatchIndex(authority, values.__getitem__)
    index.offer_many(tuple(values), now=2.0)
    expected = _oracle(authority, tuple(values.values()), now=2.0)
    ids = tuple(f"u{item.ticket}" for item in expected)
    assert index.take(50, now=2.0) == ids[:50]
    assert index.take(150, now=2.0) == ids[50:]
    assert index.take(3, now=2.0) == ()


def test_shared_tenant_change_does_not_corrupt_incremental_rank():
    authority = UnifiedSchedulingAuthority()
    values = {f"u{i}": _candidate(i) for i in range(12)}
    index = ResearchGraphDispatchIndex(authority, values.__getitem__)
    index.offer_many(tuple(values), now=3.0)
    # Parent tenant service increases, shared by every candidate in this
    # execution. New candidates must not inherit an incomparable prefix.
    authority.record_grant(tenant_id="same", flow_id="outside")
    authority.record_completion(
        tenant_id="same", flow_id="outside", service_quanta=31,
    )
    values["late"] = _candidate(30)
    index.offer_many(("late",), now=3.0)
    expected = _oracle(authority, tuple(values.values()), now=3.0)
    actual = index.take(len(values), now=3.0)
    assert actual == tuple(
        "late" if candidate.ticket == 30 else f"u{candidate.ticket}"
        for candidate in expected
    )


def test_flow_service_updates_only_its_group_and_preserves_authority_order():
    authority = UnifiedSchedulingAuthority()
    values = {f"u{i}": _candidate(i, flow=f"flow-{i%3}") for i in range(24)}
    index = ResearchGraphDispatchIndex(authority, values.__getitem__)
    index.offer_many(tuple(values), now=4.0)
    authority.record_grant(tenant_id="same", flow_id="flow-0")
    authority.record_completion(
        tenant_id="same", flow_id="flow-0", service_quanta=12,
    )
    expected = _oracle(authority, tuple(values.values()), now=4.0)
    result = index.take(len(values), now=4.0)
    assert result == tuple(f"u{item.ticket}" for item in expected)


def test_retry_parked_candidate_only_reenters_after_wakeup():
    authority = UnifiedSchedulingAuthority()
    candidate = _candidate(1)
    index = ResearchGraphDispatchIndex(authority, lambda _id: candidate)
    index.offer_many(("a",), now=1.0)
    assert index.take(1, now=1.0) == ("a",)
    index.park("a", retry_not_before_ns=10_000)
    assert index.wake_due(now_ns=9_999) == ()
    assert index.take(1, now=1.0) == ()
    assert index.wake_due(now_ns=10_000) == ("a",)
    index.offer_many(("a",), now=1.0)
    assert index.take(1, now=1.0) == ("a",)


def test_deadline_risk_transition_reorders_without_graph_scan():
    authority = UnifiedSchedulingAuthority()
    values = {
        "a": _candidate(50, flow="a", deadline=10.0, service=5.0),
        "b": _candidate(1, flow="b", deadline=10.0, service=1.0),
    }
    index = ResearchGraphDispatchIndex(authority, values.__getitem__)
    index.offer_many(("a", "b"), now=3.0)
    # At now=6, flow a reaches its latest-start risk boundary.
    assert index.take(1, now=6.0) == ("a",)


def test_durable_delta_visible_from_different_authority_connection(tmp_path):
    path = tmp_path / "scheduler.db"
    reader = DurableUnifiedSchedulingAuthority(path)
    writer = DurableUnifiedSchedulingAuthority(path)
    assert reader.service_changes_since(None) == (0, None)
    writer.record_grant(tenant_id="same", flow_id="flow-2")
    writer.record_completion(
        tenant_id="same", flow_id="flow-2", service_quanta=9,
    )
    assert reader.service_changes_since(0) == (2, frozenset({"flow-2"}))
    assert reader.service_changes_since(2) == (2, frozenset())
    # Missing replay suffix is a hard full-rebuild signal, not an empty delta.
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM unified_scheduling_events WHERE sequence=1")
    assert reader.service_changes_since(0) == (2, None)


def test_frontier_releases_only_newly_ready_once():
    digest = canonical_digest({"test": "transition"})
    nodes = tuple(
        execution_vertex(name, canonical_digest({"name": name}))
        for name in ("a", "b", "c")
    )
    graph = execution_graph(
        "delta", digest, nodes, (execution_flow("a", "b"),),
    )
    frontier = ResearchGraphDependencyFrontier(
        graph, selected_node_ids=("a", "b", "c"), terminal_results={},
    )
    pending = {"a", "b", "c"}
    assert frontier.drain_newly_ready(pending) == ("a", "c")
    assert frontier.drain_newly_ready(pending) == ()
    frontier.consume_ready("a")
    pending.remove("a")
    frontier.record_terminal(
        ResearchGraphNodeResult(
            "a", canonical_digest({"name": "a"}),
            ResearchGraphNodeState.SUCCEEDED,
        )
    )
    assert frontier.drain_newly_ready(pending) == ("b",)
    assert frontier.drain_newly_ready(pending) == ()



def test_randomized_incremental_authority_equivalence(tmp_path):
    import random

    randomizer = random.Random(20261010)
    path = tmp_path / "global.sqlite"
    authority = DurableUnifiedSchedulingAuthority(path)
    other_process = DurableUnifiedSchedulingAuthority(path)
    values = {f"u{i}": _candidate(i, flow=f"flow-{i}") for i in range(160)}
    index = ResearchGraphDispatchIndex(authority, values.__getitem__)
    index.offer_many(tuple(values), now=7.0)
    for iteration in range(70):
        remaining = tuple(values.values())
        expected = _oracle(authority, remaining, now=7.0)[0]
        actual = index.take(1, now=7.0)
        assert actual == (f"u{expected.ticket}",)
        values.pop(actual[0])
        if iteration % 2 == 0:
            impacted = f"flow-{randomizer.randrange(160)}"
            other_process.record_grant(
                tenant_id="same", flow_id=impacted,
            )
            other_process.record_completion(
                tenant_id="same", flow_id=impacted,
                service_quanta=randomizer.randrange(1, 100),
            )
        if iteration % 11 == 0:
            i = iteration + 160
            candidate = _candidate(i, flow=f"flow-{i}")
            values[f"u{i}"] = candidate
            index.offer_many((f"u{i}",), now=7.0)


def test_scheduler_full_ready_scan_path_is_disconnected():
    from pathlib import Path
    import inspect

    from noetrium_platform.composition.research_graph import ResearchGraphScheduler

    implementation = inspect.getsource(ResearchGraphScheduler._execute_durable)
    assert "next_ready_node_ids(" not in implementation
    assert "limit=len(pending)" not in implementation
    assert "drain_newly_ready(" in implementation



def test_cancelled_group_head_cannot_promote_successor_ahead_of_better_flow():
    authority = UnifiedSchedulingAuthority()
    values = {
        "bad": _candidate(0, flow="a", tenant="same"),
        "successor": _candidate(100, flow="a", tenant="same"),
        "peer": _candidate(1, flow="b", tenant="same"),
    }
    index = ResearchGraphDispatchIndex(authority, values.__getitem__)
    index.offer_many(("bad", "successor", "peer"), now=1.0)
    index.forget("bad")
    assert index.take(2, now=1.0) == ("peer", "successor")



def test_same_flow_new_offers_do_not_mix_old_and_new_service_prefix():
    authority = UnifiedSchedulingAuthority()
    values = {
        "a1": _candidate(10, flow="flow-a"),
        "a2": _candidate(20, flow="flow-a"),
        "b1": _candidate(15, flow="flow-b"),
    }
    index = ResearchGraphDispatchIndex(authority, values.__getitem__)
    index.offer_many(tuple(values), now=2.0)
    authority.record_grant(tenant_id="same", flow_id="flow-a")
    authority.record_completion(
        tenant_id="same", flow_id="flow-a", service_quanta=500,
    )
    values["a3"] = _candidate(30, flow="flow-a")
    index.offer_many(("a3",), now=2.0)
    expected = tuple(
        next(k for k, v in values.items() if v is candidate)
        for candidate in _oracle(authority, tuple(values.values()), now=2.0)
    )
    assert index.take(len(values), now=2.0) == expected


def test_retry_queue_uses_min_heap_without_revisiting_all_parked_units():
    authority = UnifiedSchedulingAuthority()
    candidate = _candidate(3)
    index = ResearchGraphDispatchIndex(authority, lambda _id: candidate)
    for i in range(1000):
        index.park(f"u{i}", retry_not_before_ns=100_000 + i)
    assert index.next_retry_ns() == 100_000
    assert index.wake_due(now_ns=99_999) == ()
    assert index.wake_due(now_ns=100_002) == ("u0", "u1", "u2")
    assert index.next_retry_ns() == 100_003
    index.park("u10", retry_not_before_ns=1)
    assert index.next_retry_ns() == 1
    assert index.wake_due(now_ns=1) == ("u10",)
    assert index.next_retry_ns() == 100_003



def test_deadline_expiry_demotes_previously_at_risk_flow():
    authority = UnifiedSchedulingAuthority()
    values = {
        "urgent": _candidate(
            50, flow="urgent", deadline=10.0, service=5.0,
        ),
        "regular": _candidate(1, flow="regular"),
    }
    index = ResearchGraphDispatchIndex(authority, values.__getitem__)
    index.offer_many(tuple(values), now=4.0)
    assert index.next_rank_transition() == 5.0
    assert index.take(1, now=6.0) == ("urgent",)
    # Put it back without clearing the flow's deferred deadline marker.
    index.offer_many(("urgent",), now=6.0)
    assert index.next_rank_transition() == 10.0
    # After expiry, the canonical authority ranks live work before expired
    # work; this must not reuse the previously cached urgency rank.
    assert index.take(1, now=10.0) == ("regular",)
    assert index.take(1, now=10.0) == ("urgent",)
