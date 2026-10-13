import pytest
from noetrium_platform.research.experimentation.api.sharding import ExperimentBatchPlacement


def test_batch_placement_rejects_invalid_digest() -> None:
    with pytest.raises(ValueError):
        ExperimentBatchPlacement(batch_id="batch:0", batch_digest="not-a-digest", shard_assignments=())
