import pytest
from noetrium_platform.research.experimentation.api.sharding import ExperimentBatchPlacement


def test_batch_placement_rejects_negative_shard_index() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ExperimentBatchPlacement(batch_id="batch:0", batch_digest="a" * 64, shard_assignments=((-1, ("b" * 64,)),))
