from __future__ import annotations

from noetrium_platform.evidence.data.state.api import AggregateValue, AtomicMutation
import noetrium_platform.evidence.data.state.runtime as state_runtime
from noetrium_platform.evidence.data.state.runtime import SQLiteAtomicStateStore


def test_atomic_state_has_one_durable_authority_and_survives_reopen(tmp_path) -> None:
    assert not hasattr(state_runtime, "InMemoryAtomicStateStore")
    path = tmp_path / "atomic.sqlite"
    initial = AggregateValue("a", 1, "g0", "d0", {"value": 0})
    store = SQLiteAtomicStateStore(path, (initial,))
    committed = store.commit_batch(
        (AtomicMutation("a", 1, "g0", "g1", "d1", {"value": 1}),)
    )
    assert committed[0].version == 2
    reopened = SQLiteAtomicStateStore(path)
    value = reopened.read("a")
    assert (value.version, value.generation, value.digest, value.payload) == (
        2,
        "g1",
        "d1",
        {"value": 1},
    )
