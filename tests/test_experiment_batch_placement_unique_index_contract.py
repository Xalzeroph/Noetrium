import pytest
from noetrium_platform.research.experimentation.api.sharding import ExperimentBatchPlacement


def test_batch_placement_rejects_duplicate_shard_index() -> None:
    with pytest.raises(ValueError, match="canonically ordered"):
        ExperimentBatchPlacement(batch_id="batch:0", batch_digest="a" * 64, shard_assignments=((0, ("b" * 64,)), (0, ("c" * 64,))))
