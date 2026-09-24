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
    ReproductionResearchOSCompileError,
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


def test_enum_paper_option_expands_all_scientific_variants_without_manual_values() -> None:
    variants = resolve_reproduction_execution_variants(
        ADACM2_REPRODUCTION,
        study_factory="build_adacm2_lvu_study",
    )

    assert {row.values["interpretation"] for row in variants} == {
        "eq6_literal",
        "eq8_consistent",
    }
    assert len(variants) == 2
    assert len({row.resolution_digest for row in variants}) == 2
    assert all(len(row.proof_digests) == 1 for row in variants)


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
