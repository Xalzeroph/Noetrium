"""Cache generation and keys must identify the same durable service cut."""
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import DurableUnifiedSchedulingAuthority
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import durable
from tests.test_durable_cross_process_scheduling_v1 import _candidate


def test_versioned_ranking_uses_one_snapshot_and_reuses_only_exact_revision(tmp_path, monkeypatch):
    path = tmp_path / 'ranking.sqlite'
    reader = DurableUnifiedSchedulingAuthority(path)
    writer = DurableUnifiedSchedulingAuthority(path)
    candidates = (_candidate(1, 'paper'), _candidate(2, 'other'))
    reads = 0
    original = durable.sqlite_read_snapshot

    def counted(*args, **kwargs):
        nonlocal reads
        reads += 1
        return original(*args, **kwargs)

    try:
        monkeypatch.setattr(durable, 'sqlite_read_snapshot', counted)
        revision, keys = reader.ordering_keys_at_revision(candidates, now_monotonic=3)
        assert reads == 1 and revision == 0 and keys is not None
        reads = 0
        assert reader.ordering_keys_at_revision(candidates, now_monotonic=3, known_revision=revision) == (revision, None)
        assert reads == 1
        writer.record_grant(tenant_id='paper', flow_id='flow-paper')
        writer.record_completion(tenant_id='paper', flow_id='flow-paper', service_quanta=9)
        reads = 0
        next_revision, next_keys = reader.ordering_keys_at_revision(candidates, now_monotonic=3, known_revision=revision)
        assert reads == 1 and next_revision == 2 and next_keys != keys
        assert next_keys == reader.ordering_keys(candidates, now_monotonic=3)
    finally:
        writer.close()
        reader.close()


def test_remote_commit_during_projection_cannot_relabel_old_keys_as_new_cut(tmp_path, monkeypatch):
    path = tmp_path / 'ranking.sqlite'
    reader = DurableUnifiedSchedulingAuthority(path)
    writer = DurableUnifiedSchedulingAuthority(path)
    candidates = (_candidate(1, 'paper'), _candidate(2, 'other'))
    old_keys = reader.ordering_keys(candidates, now_monotonic=3)
    original = reader.ordering_keys
    committed = False

    def concurrent_commit(*args, **kwargs):
        nonlocal committed
        if not committed:
            committed = True
            writer.record_grant(tenant_id='paper', flow_id='flow-paper')
            writer.record_completion(tenant_id='paper', flow_id='flow-paper', service_quanta=9)
        return original(*args, **kwargs)

    try:
        monkeypatch.setattr(reader, 'ordering_keys', concurrent_commit)
        revision, keys = reader.ordering_keys_at_revision(candidates, now_monotonic=3)
        assert revision == 0 and keys == old_keys
        next_revision, next_keys = reader.ordering_keys_at_revision(candidates, now_monotonic=3, known_revision=revision)
        assert next_revision == 2 and next_keys != old_keys
    finally:
        writer.close()
        reader.close()
