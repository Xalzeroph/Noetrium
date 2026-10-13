from pathlib import Path

from noetrium_platform.foundation.kernel.truth import TruthModality, truth_modality
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.authority.api import (
    ResourceCapacity,
    ResourceRealizationSpec,
    authority_lease,
    binding_field,
    claim_field,
    observation_field,
    physical_identity,
    realization_spec_fact,
    resource_claim,
    resource_observation,
    ticket_field,
)
from noetrium_platform.infrastructure.resources.authority.runtime.authority import (
    UniversalResourceAuthority,
)


def test_resource_authority_is_event_sourced_and_modal(tmp_path: Path) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    try:
        generation = authority.ensure_generation("gpu:0")
        authority.declare_capacity(ResourceCapacity((("gpu.memory", 100),)))

        claim_request = resource_claim(
            "claim-1",
            "gpu:0",
            "run:1",
            generation.generation,
            owner_scope=PLATFORM_SCOPE,
            scope_generation=1,
            scope_lease_id=None,
            owner_lease_id=None,
            amounts=(("gpu.memory", 25),),
        )
        assert truth_modality(claim_request) is TruthModality.DECLARED
        claim = authority.acquire_claim(claim_request)
        assert truth_modality(claim) is TruthModality.AUTHORIZED
        assert claim != claim_request

        lease_request = authority_lease(
            "lease-1",
            "gpu:0",
            "run:1",
            generation.generation,
            owner_scope=PLATFORM_SCOPE,
            scope_generation=1,
            scope_lease_id=None,
        )
        assert truth_modality(lease_request) is TruthModality.DECLARED
        lease = authority.acquire_lease(lease_request)
        assert truth_modality(lease) is TruthModality.AUTHORIZED

        spec = ResourceRealizationSpec("test-provider", {"size": 25})
        realization_key = "realization:gpu:0"
        ticket, created = authority.prepare_realization(
            realization_key=realization_key,
            resource_key="gpu:0",
            generation=generation.generation,
            spec=spec,
            holder_key="run:1",
        )
        assert created
        assert truth_modality(ticket) is TruthModality.AUTHORIZED

        same, created_again = authority.prepare_realization(
            realization_key=realization_key,
            resource_key="gpu:0",
            generation=generation.generation,
            spec=spec,
            holder_key="run:1",
        )
        assert not created_again
        assert same == ticket

        physical = physical_identity(
            "test-provider",
            "physical-1",
            {"generation": generation.generation},
        )
        assert truth_modality(physical) is TruthModality.OBSERVED
        observation = resource_observation(
            resource_key="gpu:0",
            generation=generation.generation,
            ticket_id=ticket_field(ticket, "ticket_id"),
            spec_digest=ticket_field(ticket, "spec_digest"),
            exists=True,
            ready=True,
            physical=physical,
        )
        assert truth_modality(observation) is TruthModality.OBSERVED

        binding = authority.bind(ticket_field(ticket, "ticket_id"), observation)
        assert truth_modality(binding) is TruthModality.AUTHORIZED
        assert (
            binding_field(binding, "physical_identity")
            == observation_field(observation, "physical_identity")
        )

        rebuilt = authority.verify_projection_rebuild()
        assert rebuilt == authority.snapshot()

        retiring = authority.begin_retire(ticket_field(ticket, "ticket_id"))
        absent = resource_observation(
            resource_key="gpu:0",
            generation=generation.generation,
            ticket_id=ticket_field(retiring, "ticket_id"),
            spec_digest=ticket_field(retiring, "spec_digest"),
            exists=False,
            ready=False,
        )
        authority.complete_retire(ticket_field(retiring, "ticket_id"), absent)
        authority.release_lease(lease)
        authority.release_claim(claim_field(claim, "claim_id"))

        assert authority.verify_projection_rebuild() == authority.snapshot()

        trace = authority.event_trace(resource_key="gpu:0")
        assert trace
        assert all(
            truth_modality(event)
            in {
                TruthModality.AUTHORIZED,
                TruthModality.OBSERVED,
            }
            for event in trace
        )
        assert any(
            event.attribute("truth_modality") == TruthModality.OBSERVED.value
            for event in trace
        )
        assert any(
            event.attribute("truth_modality") == TruthModality.AUTHORIZED.value
            for event in trace
        )
    finally:
        authority.close()


def test_realization_spec_is_declared_unit() -> None:
    unit = realization_spec_fact("provider", {"a": 1})
    assert truth_modality(unit) is TruthModality.DECLARED
