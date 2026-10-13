from types import SimpleNamespace
import pytest
from noetrium_platform.composition.research_graph import ResearchGraphScheduler, _DurableAttemptBook
from noetrium_platform.research.execution.graph.api import ResearchGraphExecutionConflict, ResearchGraphLiveNodeState


def scheduler_and_book():
    scheduler = object.__new__(ResearchGraphScheduler)
    scheduler._lease_ns = 30_000_000_000
    scheduler._scheduler_owner_id = "owner"
    book = _DurableAttemptBook()
    book.publish("node", "attempt", 10_000_000_000, 30_000_000_000)
    return scheduler, book


def test_periodic_timer_phase_does_not_expire_a_still_valid_lease(monkeypatch):
    scheduler, book = scheduler_and_book()
    # An early tick sees no due claim; the next tick is just beyond 2/3 TTL.
    assert not book.due(9_999_999_999)
    now = 20_100_000_000
    monkeypatch.setattr("noetrium_platform.composition.research_graph.time.time_ns", lambda: now)
    calls = []

    class Store:
        def node_state(self, *args):
            return SimpleNamespace(state=ResearchGraphLiveNodeState.RUNNING, attempt_id="attempt", lease_owner_id="owner")
        def renew_leases(self, execution_id, rows, *, now_ns, wait_timeout_seconds):
            calls.append(wait_timeout_seconds)
            return (SimpleNamespace(node_id="node"),)

    scheduler._renew_due_durable_leases(
        store=Store(), execution_id="cut", attempts=book,
        renewal_interval_ns=10_000_000_000, now_ns=now,
    )
    assert calls == [pytest.approx(9.9)]
    assert book.current("node")[2] == now + scheduler._lease_ns


def test_actual_expiry_still_fences_before_any_renewal_write(monkeypatch):
    scheduler, book = scheduler_and_book()
    now = 30_000_000_000
    monkeypatch.setattr("noetrium_platform.composition.research_graph.time.time_ns", lambda: now)

    class Store:
        def renew_leases(self, *args, **kwargs):
            pytest.fail("expired lease was renewed")
        def node_state(self, *args):
            return SimpleNamespace(state=ResearchGraphLiveNodeState.RUNNING, attempt_id="attempt", lease_owner_id="owner")

    with pytest.raises(ResearchGraphExecutionConflict, match="horizon exhausted"):
        scheduler._renew_due_durable_leases(
            store=Store(), execution_id="cut", attempts=book,
            renewal_interval_ns=10_000_000_000, now_ns=now,
        )
