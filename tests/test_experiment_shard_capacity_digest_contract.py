from noetrium_platform.research.experimentation.api.sharding import ExperimentShard


def test_worker_capacity_changes_shard_digest() -> None:
    base = dict(shard_index=0, worker_scope_id="worker:0", assignment_digests=("a" * 64,), estimated_cost_units=1)
    assert ExperimentShard(**base, capacity_units=1).shard_digest != ExperimentShard(**base, capacity_units=2).shard_digest
