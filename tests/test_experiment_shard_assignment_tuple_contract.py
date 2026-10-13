import pytest
from noetrium_platform.research.experimentation.api.sharding import ExperimentShard


def test_experiment_shard_requires_tuple_assignments() -> None:
    with pytest.raises(TypeError, match="tuple"):
        ExperimentShard(shard_index=0, worker_scope_id="worker:0", assignment_digests=[], estimated_cost_units=0)  # type: ignore[arg-type]
