from __future__ import annotations

import pytest

from noetrium_platform.capabilities.participant.capability.api.contracts import (
    CapabilityDescriptor,
)
from noetrium_platform.capabilities.participant.capability.api.selection import (
    CapabilitySelectionView,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.reproductions.adacm2_memory.definition import (
    REPRODUCTION as ADACM2_REPRODUCTION,
)
from research.reproductions.research_os import (
    ReproductionCapabilitySelectionRegistration,
    ReproductionCapabilitySelectionRegistry,
    ReproductionResearchOSCompileError,
    resolve_execution_requirements,
    resolve_reproduction_execution_variants,
)
from research.reproductions.storm_wiki.definition import (
    REPRODUCTION as STORM_REPRODUCTION,
)


class _SearchResolver:
    def resolve(self, requirement):
        assert requirement.package == "storm_wiki"
        assert requirement.parameter == "search_capability_id"
        return CapabilitySelectionView(
            source_cut_digest=canonical_digest({"capability-cut": "test"}),
            selection_provenance_digest=canonical_digest(
                {"selector": "storm-search"}
            ),
            descriptors=(
                CapabilityDescriptor(
                    "search.web",
                    "v1",
                    "search.request.v1",
                    "search.result.v1",
                ),
            ),
        )


def test_adacm2_paper_interpretations_are_explicit_study_lanes() -> None:
    eq6 = resolve_reproduction_execution_variants(
        ADACM2_REPRODUCTION,
        study_factory="build_adacm2_lvu_eq6_literal_study",
    )
    eq8 = resolve_reproduction_execution_variants(
        ADACM2_REPRODUCTION,
        study_factory="build_adacm2_lvu_eq8_consistent_study",
    )

    assert len(eq6) == len(eq8) == 1
    assert eq6[0].values == eq8[0].values == {}
    assert eq6[0].study_factory != eq8[0].study_factory
    assert eq6[0].resolution_digest != eq8[0].resolution_digest
    assert eq6[0].proof_digests == eq8[0].proof_digests == ()


def test_capability_requirement_uses_authoritative_selection_view_proof() -> None:
    variants = resolve_reproduction_execution_variants(
        STORM_REPRODUCTION,
        study_factory="build_storm_freshwiki_study",
        capability_resolver=_SearchResolver(),
    )

    assert len(variants) == 1
    variant = variants[0]
    assert variant.values == {"search_capability_id": "search.web"}
    assert len(variant.proof_digests) == 1
    assert len(variant.proof_digests[0]) == 64


def test_capability_requirement_never_invents_default_provider() -> None:
    with pytest.raises(
        ReproductionResearchOSCompileError,
        match="requires platform capability resolution",
    ):
        resolve_reproduction_execution_variants(
            STORM_REPRODUCTION,
            study_factory="build_storm_freshwiki_study",
        )



def test_capability_registry_closes_exact_reproduction_requirement() -> None:
    requirement = next(
        row
        for row in resolve_execution_requirements(STORM_REPRODUCTION)
        if row.parameter == "search_capability_id"
    )
    view = CapabilitySelectionView(
        source_cut_digest=canonical_digest({"capability-cut": "registry"}),
        selection_provenance_digest=canonical_digest(
            {"selector": "registry-search"}
        ),
        descriptors=(
            CapabilityDescriptor(
                "search.web",
                "v1",
                "search.request.v1",
                "search.result.v1",
            ),
        ),
    )
    registry = ReproductionCapabilitySelectionRegistry(
        (
            ReproductionCapabilitySelectionRegistration(
                requirement.requirement_digest,
                view,
            ),
        )
    )

    variants = resolve_reproduction_execution_variants(
        STORM_REPRODUCTION,
        study_factory="build_storm_freshwiki_study",
        capability_resolver=registry,
    )

    assert len(variants) == 1
    assert variants[0].values == {"search_capability_id": "search.web"}
    assert len(registry.identity_digest) == 64


def test_capability_registry_never_falls_back_to_unregistered_requirement() -> None:
    registry = ReproductionCapabilitySelectionRegistry(())
    with pytest.raises(LookupError, match="no exact CapabilitySelectionView"):
        resolve_reproduction_execution_variants(
            STORM_REPRODUCTION,
            study_factory="build_storm_freshwiki_study",
            capability_resolver=registry,
        )
