import pytest
from noetrium_platform.research.experimentation.api.sharding import ExperimentShard


def test_experiment_shard_rejects_duplicate_assignments() -> None:
    digest = "a" * 64
    with pytest.raises(ValueError, match="unique"):
        ExperimentShard(shard_index=0, worker_scope_id="worker:0", assignment_digests=(digest, digest), estimated_cost_units=2)
