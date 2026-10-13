"""Per-Unit candidate projection reuse never caches global scheduling truth."""
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.concurrency.scheduling.api import ExecutionPriority
from noetrium_platform.research.execution.graph.api import execution_vertex
from noetrium_platform.composition.research_graph import ResearchGraphScheduler


def _scheduler():
    # Candidate projection is pure declared Unit data + local attempt evidence.
    # No global scheduling Authority is required to construct the candidate;
    # real admission still requires it.
    scheduler = object.__new__(ResearchGraphScheduler)
    scheduler._scheduling_history = {}
    scheduler._scheduling_ready_since = {}
    scheduler._scheduling_candidates = {}
    scheduler._tenant_id = "bench"
    scheduler._priority = ExecutionPriority.NORMAL
    scheduler._critical_path_tail_work_by_node = {"a": 10.0, "b": 3.0}
    return scheduler


def test_unit_candidate_reuses_identity_until_its_scientific_service_history_changes():
    scheduler = _scheduler()
    semantic = canonical_digest({"shared-method": 1})
    a = execution_vertex("a", semantic, effectful=True, static_cost=7)
    b = execution_vertex("b", semantic, static_cost=1)
    first = scheduler._scheduling_candidate(a, deadline=None)
    assert scheduler._scheduling_candidate(a, deadline=None) is first
    other = scheduler._scheduling_candidate(b, deadline=None)
    assert other is scheduler._scheduling_candidate(b, deadline=None)
    assert other is not first
    assert first.critical_path_tail_work == 10.0
    assert other.critical_path_tail_work == 3.0
    assert first.speculation_rank == 1
    assert other.speculation_rank == 0

    # Another instance of the same semantic method finishes. All cached
    # candidates with that semantic digest become stale by exact evidence
    # comparison, even if their own Unit has never been executed.
    scheduler._scheduling_history[semantic] = (2, 1, 10_000_000_000)
    refreshed = scheduler._scheduling_candidate(a, deadline=None)
    assert refreshed is not first
    assert scheduler._scheduling_candidate(a, deadline=None) is refreshed
    assert refreshed.estimated_service_seconds == 5.0
    assert refreshed.expected_waste_cost == 2.5
    assert scheduler._scheduling_candidate(b, deadline=None) is not other


def test_candidate_reuse_keeps_static_attributes_and_different_semantics_separate():
    scheduler = _scheduler()
    a = execution_vertex("a", canonical_digest({"method": 1}), static_cost=8)
    b = execution_vertex("b", canonical_digest({"method": 2}), static_cost=2)
    first = scheduler._scheduling_candidate(a, deadline=None)
    other = scheduler._scheduling_candidate(b, deadline=None)
    scheduler._scheduling_history[canonical_digest({"method": 2})] = (1, 0, 5)
    assert scheduler._scheduling_candidate(a, deadline=None) is first
    assert scheduler._scheduling_candidate(b, deadline=None) is not other
    assert first.estimated_service_cost == 8.0
    assert other.estimated_service_cost == 2.0


def test_deadline_revision_invalidates_local_candidate():
    from types import SimpleNamespace
    scheduler = _scheduler()
    node = execution_vertex("a", canonical_digest({"method": "deadline"}))
    first = SimpleNamespace(monotonic_deadline=100.0)
    second = SimpleNamespace(monotonic_deadline=200.0)
    original = scheduler._scheduling_candidate(node, deadline=first)
    assert scheduler._scheduling_candidate(node, deadline=first) is original
    later = scheduler._scheduling_candidate(node, deadline=second)
    assert later is not original
    assert later.deadline_monotonic == 200.0
    assert scheduler._scheduling_candidate(node, deadline=None).deadline_monotonic is None
