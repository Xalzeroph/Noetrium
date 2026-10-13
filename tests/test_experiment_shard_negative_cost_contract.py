import pytest
from noetrium_platform.research.experimentation.api.sharding import ExperimentShard


def test_experiment_shard_rejects_negative_cost() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ExperimentShard(shard_index=0, worker_scope_id="worker:0", assignment_digests=(), estimated_cost_units=-1)
