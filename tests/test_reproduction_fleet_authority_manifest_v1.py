from __future__ import annotations

import pytest

from research.reproductions.execution_authority import (
    ReproductionFleetAuthorityManifest,
)


def _manifest(**overrides) -> ReproductionFleetAuthorityManifest:
    values = {
        "manifest_registry_digest": "1" * 64,
        "research_capability_registry_digest": "2" * 64,
        "participant_registry_digest": "3" * 64,
        "model_registry_digest": "4" * 64,
        "trial_provider_registry_digest": "5" * 64,
        "reconciliation_registry_digest": "6" * 64,
        "benchmark_registry_digest": "7" * 64,
        "reproduction_capability_registry_digest": "8" * 64,
    }
    values.update(overrides)
    return ReproductionFleetAuthorityManifest(**values)


def test_fleet_authority_manifest_is_stable_over_same_owner_cut() -> None:
    first = _manifest()
    second = _manifest()
    assert first == second
    assert len(first.manifest_digest) == 64


@pytest.mark.parametrize(
    "field_name",
    (
        "manifest_registry_digest",
        "research_capability_registry_digest",
        "participant_registry_digest",
        "model_registry_digest",
        "trial_provider_registry_digest",
        "reconciliation_registry_digest",
        "benchmark_registry_digest",
        "reproduction_capability_registry_digest",
    ),
)
def test_every_owner_registry_changes_fleet_authority_identity(
    field_name: str,
) -> None:
    baseline = _manifest()
    changed = _manifest(**{field_name: "9" * 64})
    assert changed.manifest_digest != baseline.manifest_digest


def test_fleet_authority_manifest_rejects_unproven_identity() -> None:
    with pytest.raises(ValueError):
        _manifest(benchmark_registry_digest="not-a-digest")
