from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.infrastructure.resources.authority import (
    ResourceCapacity,
    UniversalResourceAuthority,
)


def test_ensure_capacity_is_idempotent_and_rejects_drift(tmp_path: Path) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    try:
        capacity = ResourceCapacity((("model-slot:test-generation", 4),))
        authority.ensure_capacity(capacity)
        event_count = len(authority.event_trace())

        authority.ensure_capacity(capacity)
        assert len(authority.event_trace()) == event_count

        with pytest.raises(ValueError, match="immutable resource capacity drift"):
            authority.ensure_capacity(
                ResourceCapacity((("model-slot:test-generation", 5),))
            )

        authority.verify_projection_rebuild()
    finally:
        authority.close()
