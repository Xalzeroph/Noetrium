import pytest
from noetrium_platform.research.experimentation.api.sharding import ExperimentBatchPlacement


def test_batch_placement_rejects_noncanonical_shard_order() -> None:
    with pytest.raises(ValueError, match="canonically ordered"):
        ExperimentBatchPlacement(batch_id="batch:0", batch_digest="a" * 64, shard_assignments=((1, ("b" * 64,)), (0, ("c" * 64,))))
