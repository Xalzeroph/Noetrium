import pytest

from noetrium_platform.research.experimentation.api.sharding import ExperimentShard


def test_experiment_shard_rejects_boolean_index() -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        ExperimentShard(
            shard_index=True,
            worker_scope_id="worker:0",
            assignment_digests=(),
            estimated_cost_units=0,
        )
