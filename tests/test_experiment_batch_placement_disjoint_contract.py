import pytest
from noetrium_platform.research.experimentation.api.sharding import ExperimentBatchPlacement


def test_batch_placement_rejects_overlapping_assignments() -> None:
    digest = "b" * 64
    with pytest.raises(ValueError, match="disjoint"):
        ExperimentBatchPlacement(batch_id="batch:0", batch_digest="a" * 64, shard_assignments=((0, (digest,)), (1, (digest,))))
