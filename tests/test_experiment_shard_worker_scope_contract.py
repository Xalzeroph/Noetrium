import pytest
from noetrium_platform.research.experimentation.api.sharding import ExperimentShard


def test_experiment_shard_rejects_blank_worker_scope() -> None:
    with pytest.raises(ValueError, match="worker_scope_id"):
        ExperimentShard(shard_index=0, worker_scope_id="  ", assignment_digests=(), estimated_cost_units=0)
