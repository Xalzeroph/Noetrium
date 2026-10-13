import pytest
from noetrium_platform.research.experimentation.api.sharding import ExperimentBatchPlacement


def test_batch_placement_rejects_blank_id() -> None:
    with pytest.raises(ValueError, match="batch_id"):
        ExperimentBatchPlacement(batch_id=" ", batch_digest="a" * 64, shard_assignments=())
