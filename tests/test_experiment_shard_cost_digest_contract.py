from noetrium_platform.research.experimentation.api.sharding import ExperimentShard


def test_estimated_cost_changes_shard_digest() -> None:
    common = dict(shard_index=0, worker_scope_id="worker:0", assignment_digests=("a" * 64,))
    assert ExperimentShard(**common, estimated_cost_units=1).shard_digest != ExperimentShard(**common, estimated_cost_units=2).shard_digest
