"""Exact checkpoint recovery from the single durable scheduling event ledger."""
from __future__ import annotations

import sqlite3

import pytest

from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
    DurableUnifiedSchedulingAuthority,
)
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
    durable,
)


def _seed(path, *, count: int) -> DurableUnifiedSchedulingAuthority:
    authority = DurableUnifiedSchedulingAuthority(path)
    for index in range(count):
        name = f"flow-{index % 3}"
        authority.record_grant(
            tenant_id="paper", resource_id="gpu", flow_id=name,
            reserved_service_quanta=1,
        )
        authority.record_completion(
            tenant_id="paper", resource_id="gpu", flow_id=name,
            service_quanta=1, reserved_service_quanta=1,
        )
    return authority


def test_checkpoint_recovers_exact_fairness_with_bounded_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr(durable, "_CHECKPOINT_INTERVAL", 8)
    path = tmp_path / "authority.sqlite"
    writer = _seed(path, count=19)
    assert writer.service_revision() == 38

    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT sequence, sha256 FROM unified_scheduling_checkpoint WHERE id=1"
        ).fetchone()
        assert row is not None
        checkpoint_sequence, digest = row
        assert checkpoint_sequence == 32
        assert len(digest) == 64
        assert conn.execute(
            "SELECT COUNT(*) FROM unified_scheduling_events"
        ).fetchone()[0] == 38

    cold = DurableUnifiedSchedulingAuthority(path)
    original = cold._load_checkpoint
    recovered_cuts = []

    def record_checkpoint_cut(conn):
        original(conn)
        recovered_cuts.append(cold._applied)

    cold._load_checkpoint = record_checkpoint_cut
    assert cold.service_revision() == 38
    assert recovered_cuts[0] == 32
    assert cold._checkpoint_cut == 32
    assert cold._grant_sequence == writer._grant_sequence
    for entity_kind in ("tenant", "resource", "flow"):
        source = getattr(writer, f"_{entity_kind}_states")
        restored = getattr(cold, f"_{entity_kind}_states")
        assert set(source) == set(restored)
        for key in source:
            source_state = source[key]
            restored_state = restored[key]
            assert (
                source_state.in_flight,
                source_state.service_quanta,
                source_state.reserved_service_quanta,
                source_state.last_grant,
                source_state.last_completion,
                source_state.retire_requested,
                source_state.parent,
            ) == (
                restored_state.in_flight,
                restored_state.service_quanta,
                restored_state.reserved_service_quanta,
                restored_state.last_grant,
                restored_state.last_completion,
                restored_state.retire_requested,
                restored_state.parent,
            )
    assert cold._recorded_flow_coordinates == writer._recorded_flow_coordinates
    assert cold.record_grant(
        tenant_id="paper", resource_id="gpu", flow_id="flow-1",
        reserved_service_quanta=2,
    ) == writer._grant_sequence + 1
    cold.record_completion(
        tenant_id="paper", resource_id="gpu", flow_id="flow-1",
        reserved_service_quanta=2, service_quanta=3,
    )
    assert DurableUnifiedSchedulingAuthority(path).service_revision() == 40


def test_corrupted_checkpoint_fails_closed_without_claiming_fairness(tmp_path, monkeypatch):
    monkeypatch.setattr(durable, "_CHECKPOINT_INTERVAL", 4)
    path = tmp_path / "authority.sqlite"
    _seed(path, count=4)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE unified_scheduling_checkpoint SET payload='{}' WHERE id=1"
        )
    cold = DurableUnifiedSchedulingAuthority(path)
    with pytest.raises(RuntimeError, match="checkpoint digest drift"):
        cold.service_revision()
    assert cold._applied == 0


def test_checkpoint_cannot_claim_events_beyond_committed_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(durable, "_CHECKPOINT_INTERVAL", 4)
    path = tmp_path / "authority.sqlite"
    _seed(path, count=4)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE unified_scheduling_checkpoint SET sequence=100000 WHERE id=1"
        )
    with pytest.raises(RuntimeError, match="exceeds journal cut"):
        DurableUnifiedSchedulingAuthority(path).service_revision()

def test_warm_scheduler_constructor_avoids_shared_writer(tmp_path, monkeypatch):
    from contextlib import contextmanager

    path = tmp_path / "authority.sqlite"
    first = DurableUnifiedSchedulingAuthority(path)
    assert first.record_grant(tenant_id="paper", flow_id="warm") == 1

    @contextmanager
    def forbidden_writer(*args, **kwargs):
        raise AssertionError("warm scheduler constructor must not take SQLite writer")
        yield

    monkeypatch.setattr(durable, "durable_sqlite_connection", forbidden_writer)
    fresh = DurableUnifiedSchedulingAuthority(path)
    assert fresh.service_revision() == 1


def test_partially_materialized_schema_is_recovered_atomically(tmp_path):
    import sqlite3

    path = tmp_path / "authority.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(durable._SCHEMA)
    scheduler = DurableUnifiedSchedulingAuthority(path)
    assert scheduler.record_grant(tenant_id="paper", flow_id="repaired") == 1
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name='unified_scheduling_checkpoint'"
        ).fetchone() is not None

def test_scheduler_reuses_one_writer_and_closes_at_lifetime_end(tmp_path):
    path = tmp_path / "authority.sqlite"
    scheduler = DurableUnifiedSchedulingAuthority(path)
    assert scheduler._writers.open_count == 0
    for index in range(4):
        name = f"run-{index}"
        scheduler.record_grant(tenant_id="paper", flow_id=name)
        scheduler.record_completion(tenant_id="paper", flow_id=name, service_quanta=1)
    assert scheduler._writers.open_count == 1
    scheduler.close()
    scheduler.close()
    with pytest.raises(RuntimeError, match="closed"):
        scheduler.record_grant(tenant_id="paper", flow_id="after-close")
    with pytest.raises(RuntimeError, match="closed"):
        scheduler.service_revision()
    assert DurableUnifiedSchedulingAuthority(path).service_revision() == 8
