import pytest
from noetrium_platform.research.experimentation.api.sharding import ExperimentBatchPlacement


def test_batch_placement_rejects_empty_assignment_group() -> None:
    with pytest.raises(ValueError, match="requires assignments"):
        ExperimentBatchPlacement(batch_id="batch:0", batch_digest="a" * 64, shard_assignments=((0, ()),))
