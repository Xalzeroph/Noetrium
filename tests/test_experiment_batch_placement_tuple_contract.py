import pytest
from noetrium_platform.research.experimentation.api.sharding import ExperimentBatchPlacement


def test_batch_placement_requires_tuple_rows() -> None:
    with pytest.raises(TypeError, match="tuple"):
        ExperimentBatchPlacement(batch_id="batch:0", batch_digest="a" * 64, shard_assignments=[])  # type: ignore[arg-type]
