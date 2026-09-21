from noetrium_platform.research.experimentation.api.sharding import ExperimentShard


def test_experiment_shard_digest_is_deterministic() -> None:
    first = ExperimentShard(shard_index=0, worker_scope_id="worker:0", assignment_digests=("a" * 64,), estimated_cost_units=1)
    second = ExperimentShard(shard_index=0, worker_scope_id="worker:0", assignment_digests=("a" * 64,), estimated_cost_units=1)
    assert first.shard_digest == second.shard_digest
