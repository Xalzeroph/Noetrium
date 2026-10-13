from noetrium_platform.capabilities.model.serving.endpoint.api.replica import (
    ModelEndpointReplicaSelectionCandidate,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    DeficitPrefixPressureReplicaSelectionPolicy,
    PinnedReplicaSelectionPolicy,
)


def _candidate(
    deployment_id: str,
    *,
    capacity: int = 4,
    in_flight: int = 0,
    attempted: bool = False,
    affinity: float = 0.0,
    depth: int = 0,
    waiting: int = 0,
    observed: bool = True,
    kv: float = 0.0,
    deficit: bool = True,
    longest: bool = False,
) -> ModelEndpointReplicaSelectionCandidate:
    return ModelEndpointReplicaSelectionCandidate(
        deployment_id=deployment_id,
        capacity=capacity,
        in_flight=in_flight,
        completed=0,
        failures=0,
        selections=0,
        consecutive_failures=0,
        ewma_latency_seconds=None,
        last_selected_sequence=0,
        attempted_in_dispatch=attempted,
        prefix_affinity_score=affinity,
        prefix_affinity_depth=depth,
        runtime_requests_waiting=waiting,
        runtime_gpu_kv_cache_usage=kv,
        runtime_pressure_observed=observed,
        worker_deficit_positive=deficit,
        global_longest_prefix_match=longest,
    )


def test_longest_prefix_worker_wins_inside_positive_deficit_set() -> None:
    policy = DeficitPrefixPressureReplicaSelectionPolicy()
    selected = policy.select(
        (
            _candidate(
                "cached",
                in_flight=1,
                affinity=0.25,
                depth=1,
                longest=True,
            ),
            _candidate("idle", in_flight=0),
        )
    )
    assert selected == "cached"


def test_exhausted_longest_prefix_worker_yields_to_positive_deficit_worker() -> None:
    policy = DeficitPrefixPressureReplicaSelectionPolicy()
    selected = policy.select(
        (
            _candidate(
                "cached",
                affinity=1.0,
                depth=4,
                longest=True,
                deficit=False,
            ),
            _candidate("available", deficit=True),
        )
    )
    assert selected == "available"


def test_longest_prefix_precedes_cross_worker_queue_pressure() -> None:
    policy = DeficitPrefixPressureReplicaSelectionPolicy()
    selected = policy.select(
        (
            _candidate(
                "queued-cache",
                affinity=1.0,
                depth=4,
                longest=True,
                waiting=2,
            ),
            _candidate("clear", waiting=0),
        )
    )
    assert selected == "queued-cache"


def test_pressure_breaks_tie_between_longest_prefix_workers() -> None:
    policy = DeficitPrefixPressureReplicaSelectionPolicy()
    selected = policy.select(
        (
            _candidate(
                "queued-cache",
                affinity=1.0,
                depth=4,
                longest=True,
                waiting=2,
            ),
            _candidate(
                "clear-cache",
                affinity=1.0,
                depth=4,
                longest=True,
                waiting=0,
            ),
        )
    )
    assert selected == "clear-cache"


def test_known_clear_pressure_beats_unknown_inside_same_worker_class() -> None:
    policy = DeficitPrefixPressureReplicaSelectionPolicy()
    selected = policy.select(
        (
            _candidate(
                "unknown",
                observed=False,
                longest=True,
            ),
            _candidate(
                "known-clear",
                observed=True,
                longest=True,
            ),
        )
    )
    assert selected == "known-clear"


def test_saturation_dominates_longest_prefix_locality() -> None:
    policy = DeficitPrefixPressureReplicaSelectionPolicy()
    selected = policy.select(
        (
            _candidate(
                "full-cache",
                capacity=1,
                in_flight=1,
                affinity=1.0,
                depth=4,
                longest=True,
            ),
            _candidate("free", capacity=1, in_flight=0),
        )
    )
    assert selected == "free"


def test_retry_diversity_dominates_longest_prefix_locality() -> None:
    policy = DeficitPrefixPressureReplicaSelectionPolicy()
    selected = policy.select(
        (
            _candidate(
                "already-tried",
                attempted=True,
                affinity=1.0,
                depth=4,
                longest=True,
            ),
            _candidate("fresh", attempted=False),
        )
    )
    assert selected == "fresh"


def test_pressure_breaks_tie_for_replicated_longest_prefix() -> None:
    policy = DeficitPrefixPressureReplicaSelectionPolicy()
    selected = policy.select(
        (
            _candidate(
                "busy-cache",
                in_flight=2,
                affinity=1.0,
                depth=4,
                longest=True,
            ),
            _candidate(
                "light-cache",
                in_flight=0,
                affinity=1.0,
                depth=4,
                longest=True,
            ),
        )
    )
    assert selected == "light-cache"


def test_replica_selection_evaluates_each_candidate_queue_rank_once(monkeypatch) -> None:
    policy = DeficitPrefixPressureReplicaSelectionPolicy()
    original = DeficitPrefixPressureReplicaSelectionPolicy._queue_confidence_rank
    calls = 0

    def counted(candidate):
        nonlocal calls
        calls += 1
        return original(candidate)

    monkeypatch.setattr(
        DeficitPrefixPressureReplicaSelectionPolicy,
        "_queue_confidence_rank",
        staticmethod(counted),
    )
    candidates = tuple(
        _candidate(
            f"replica-{index}",
            in_flight=index % 3,
            affinity=(0.75 if index == 7 else 0.25),
            depth=(4 if index == 7 else 1),
            waiting=index % 2,
            observed=True,
        )
        for index in range(32)
    )
    assert policy.select(candidates)
    assert calls == len(candidates)


def test_replica_selection_accepts_stream_without_materialization() -> None:
    policy = DeficitPrefixPressureReplicaSelectionPolicy()
    candidates = (
        _candidate(f"replica-{index}", in_flight=index)
        for index in range(4)
    )
    assert policy.select(candidates) == "replica-0"


def test_pinned_replica_must_be_present_in_eligible_stream() -> None:
    policy = PinnedReplicaSelectionPolicy("replica-2")
    assert policy.select(
        (_candidate("replica-1"), _candidate("replica-2"))
    ) == "replica-2"
    try:
        policy.select((_candidate("replica-1"),))
    except ValueError as exc:
        assert "not currently eligible" in str(exc)
    else:
        raise AssertionError("ineligible pinned replica must fail closed")
