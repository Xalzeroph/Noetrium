from noetrium_platform.research.experimentation.api.sharding import ExperimentShard


def test_worker_scope_changes_shard_digest() -> None:
    common = dict(shard_index=0, assignment_digests=("a" * 64,), estimated_cost_units=1)
    assert ExperimentShard(**common, worker_scope_id="worker:0").shard_digest != ExperimentShard(**common, worker_scope_id="worker:1").shard_digest
