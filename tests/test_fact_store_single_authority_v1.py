from __future__ import annotations

import noetrium_platform.evidence.data.fact.composition as fact_composition
import noetrium_platform.evidence.data.fact.runtime as fact_runtime
from noetrium_platform.evidence.data.fact.api import DurableFact, DurableFactStorePort, FactCriticality
from noetrium_platform.evidence.data.fact.composition import compose_sqlite_fact_store


def test_fact_store_has_one_durable_authority_and_survives_reopen(tmp_path):
    assert not hasattr(fact_runtime, "InMemoryDurableFactStore")
    assert not hasattr(fact_composition, "compose_in_memory_fact_store")

    path = tmp_path / "facts.sqlite"
    store = compose_sqlite_fact_store(path)
    assert isinstance(store, DurableFactStorePort)
    fact = DurableFact(
        fact_id="fixture:fact:1",
        fact_type="fixture",
        schema_version="1",
        criticality=FactCriticality.REQUIRED,
        payload={"value": 1},
     )
    receipt = store.append(fact)
    assert receipt.sequence == 1
    assert store.get(fact.fact_id) == fact
    assert store.count() == 1

    reopened = compose_sqlite_fact_store(path)
    assert reopened.get(fact.fact_id) == fact
    assert reopened.count() == 1
