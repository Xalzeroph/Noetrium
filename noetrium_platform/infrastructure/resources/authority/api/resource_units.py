"""Resource authority schemas over the universal NoetriumUnit carrier."""
from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
import math
from types import MappingProxyType

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest, freeze_json, require_sha256
from noetrium_platform.foundation.kernel.unit import NoetriumUnit, role
from noetrium_platform.foundation.kernel.truth import TruthModality, modal_attributes, truth_modality
from noetrium_platform.foundation.governance.api import is_scope_unit


class TicketState(StrEnum):
    PREPARED = "prepared"
    BOUND = "bound"
    RETIRING = "retiring"
    RETIRED = "retired"


def _text(value: str, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def _positive_generation(value: int, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} generation must be positive")
    return value


def _mapping(value: Mapping[str, JsonValue] | None) -> Mapping[str, JsonValue]:
    frozen = freeze_json({} if value is None else dict(value))
    if not isinstance(frozen, Mapping):
        raise TypeError("resource unit mapping must remain an object")
    return frozen


def _record_id(kind: str, payload: object) -> str:
    return f"resource.{kind}:{canonical_digest(payload)}"



def _scope(value: NoetriumUnit) -> NoetriumUnit:
    if not is_scope_unit(value):
        raise TypeError("resource ownership requires scope Unit")
    return value


def _owned_roles(owner_scope: NoetriumUnit):
    return (role("owner_scope", _scope(owner_scope)),)


def _owner_scope(unit: NoetriumUnit) -> NoetriumUnit:
    values = unit.units("owner_scope")
    if len(values) != 1 or not is_scope_unit(values[0]):
        raise TypeError("resource ownership Unit must contain exactly one owner_scope")
    return values[0]

def resource_claim(
    claim_id: str,
    resource_key: str,
    holder_key: str,
    generation: int,
    *,
    owner_scope: NoetriumUnit,
    scope_generation: int,
    scope_lease_id: str | None,
    owner_lease_id: str | None,
    amounts: tuple[tuple[str, int], ...] = (),
    shared: tuple[str, ...] = (),
    exclusive: tuple[str, ...] = (),
    attributes: Mapping[str, JsonValue] | None = None,
    modality: TruthModality = TruthModality.DECLARED,
) -> NoetriumUnit:
    claim_id = _text(claim_id, "claim id")
    resource_key = _text(resource_key, "claim resource")
    holder_key = _text(holder_key, "claim holder")
    generation = _positive_generation(generation, "claim")
    scope_generation = _positive_generation(scope_generation, "claim scope")
    owner = _scope(owner_scope)
    scope_lease = (
        None
        if scope_lease_id is None
        else _text(scope_lease_id, "claim scope lease")
    )
    owner_lease = (
        None
        if owner_lease_id is None
        else _text(owner_lease_id, "claim owner lease")
    )
    amounts = tuple(sorted((_text(k, "claim dimension"), int(v)) for k, v in amounts))
    if any(v < 0 for _, v in amounts) or len({k for k, _ in amounts}) != len(amounts):
        raise ValueError("claim amounts must be unique non-negative dimensions")
    shared = tuple(sorted(_text(v, "shared claim token") for v in shared))
    exclusive = tuple(sorted(_text(v, "exclusive claim token") for v in exclusive))
    if len(set(shared)) != len(shared) or len(set(exclusive)) != len(exclusive):
        raise ValueError("claim tokens must be unique")
    if set(shared) & set(exclusive):
        raise ValueError("one claim token cannot be both shared and exclusive")
    attrs = _mapping(attributes)
    payload = {
        "claim_id": claim_id,
        "resource_key": resource_key,
        "holder_key": holder_key,
        "generation": generation,
        "scope_generation": scope_generation,
        "scope_lease_id": scope_lease,
        "owner_lease_id": owner_lease,
        "amounts": amounts,
        "shared": shared,
        "exclusive": exclusive,
        "attributes": attrs,
    }
    modality = TruthModality(modality)
    semantic = {**payload, "owner_scope": owner.unit_digest}
    digest = canonical_digest({"payload": semantic, "truth_modality": modality.value})
    return NoetriumUnit._from_normalized(
        _record_id("claim", semantic),
        schemas=("resource.claim",),
        attributes=MappingProxyType({
            "attributes": attrs,
            "amounts": amounts,
            "claim_id": claim_id,
            "exclusive": exclusive,
            "generation": generation,
            "holder_key": holder_key,
            "kind": "resource.claim",
            "owner_lease_id": owner_lease,
            "resource_key": resource_key,
            "scope_generation": scope_generation,
            "scope_lease_id": scope_lease,
            "shared": shared,
            "truth_modality": modality.value,
        }),
        roles=(("owner_scope", (owner,)),),
        semantic_projection_digest=digest,
    )

def is_resource_claim(value: object) -> bool:
    return type(value) is NoetriumUnit and value.attribute("kind") == "resource.claim"


def claim_field(claim: NoetriumUnit, name: str):
    if not is_resource_claim(claim):
        raise TypeError("resource claim projection requires resource.claim Unit")
    if name == "owner_scope":
        return _owner_scope(claim)
    return claim.attribute(name)


def authority_lease(
    lease_id: str,
    resource_key: str,
    holder_key: str,
    generation: int,
    *,
    owner_scope: NoetriumUnit,
    scope_generation: int,
    scope_lease_id: str | None = None,
    expires_at_epoch_s: float | None = None,
    released: bool = False,
    acquired_at_epoch_s: float | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
    modality: TruthModality = TruthModality.DECLARED,
) -> NoetriumUnit:
    lease_id = _text(lease_id, "lease id")
    resource_key = _text(resource_key, "lease resource")
    holder_key = _text(holder_key, "lease holder")
    generation = _positive_generation(generation, "lease")
    scope_generation = _positive_generation(scope_generation, "lease scope")
    owner = _scope(owner_scope)
    scope_lease = None if scope_lease_id is None else _text(scope_lease_id, "scope lease id")
    for label, value in (("lease expiry", expires_at_epoch_s), ("lease acquisition", acquired_at_epoch_s)):
        if value is not None and (not math.isfinite(float(value)) or float(value) <= 0):
            raise ValueError(f"{label} must be finite and positive")
    if acquired_at_epoch_s is not None and expires_at_epoch_s is not None and float(acquired_at_epoch_s) >= float(expires_at_epoch_s):
        raise ValueError("lease acquisition must precede expiry")
    if type(released) is not bool:
        raise TypeError("lease released must be bool")
    payload = {
        "lease_id": lease_id,
        "resource_key": resource_key,
        "holder_key": holder_key,
        "generation": generation,
        "scope_generation": scope_generation,
        "scope_lease_id": scope_lease,
        "expires_at_epoch_s": expires_at_epoch_s,
        "released": released,
        "acquired_at_epoch_s": acquired_at_epoch_s,
        "metadata": _mapping(metadata),
    }
    semantic = {**payload, "owner_scope": owner.unit_digest}
    modality = TruthModality(modality)
    return NoetriumUnit._from_normalized(
        _record_id("lease", semantic),
        schemas=("resource.lease",),
        attributes=MappingProxyType({
            "acquired_at_epoch_s": acquired_at_epoch_s,
            "expires_at_epoch_s": expires_at_epoch_s,
            "generation": generation,
            "holder_key": holder_key,
            "kind": "resource.lease",
            "lease_id": lease_id,
            "metadata": payload["metadata"],
            "released": released,
            "resource_key": resource_key,
            "scope_generation": scope_generation,
            "scope_lease_id": scope_lease,
            "truth_modality": modality.value,
        }),
        roles=(("owner_scope", (owner,)),),
    )

def is_authority_lease(value: object) -> bool:
    return type(value) is NoetriumUnit and value.attribute("kind") == "resource.lease"


def lease_field(lease: NoetriumUnit, name: str):
    if not is_authority_lease(lease):
        raise TypeError("authority lease projection requires resource.lease Unit")
    if name == "owner_scope":
        return _owner_scope(lease)
    return lease.attribute(name)


def lease_live_at(
    lease: NoetriumUnit,
    now_epoch_s: float,
    *,
    current_generation: int,
) -> bool:
    if not is_authority_lease(lease):
        raise TypeError("lease_live_at requires resource.lease Unit")
    _positive_generation(current_generation, "current")
    now = float(now_epoch_s)
    if not math.isfinite(now) or now <= 0:
        raise ValueError("lease observation time must be finite and positive")
    expiry = lease_field(lease, "expires_at_epoch_s")
    return (
        not bool(lease_field(lease, "released"))
        and int(lease_field(lease, "generation")) == current_generation
        and (expiry is None or float(expiry) > now)
    )


def realization_ticket(
    ticket_id: str,
    effect_id: str,
    realization_key: str,
    resource_key: str,
    provider_kind: str,
    generation: int,
    spec_digest: str,
    holder_key: str,
    state: TicketState = TicketState.PREPARED,
    *,
    modality: TruthModality = TruthModality.AUTHORIZED,
) -> NoetriumUnit:
    payload = {
        "ticket_id": _text(ticket_id, "ticket id"),
        "effect_id": _text(effect_id, "effect id"),
        "realization_key": _text(realization_key, "realization key"),
        "resource_key": _text(resource_key, "ticket resource"),
        "provider_kind": _text(provider_kind, "provider kind"),
        "generation": _positive_generation(generation, "ticket"),
        "spec_digest": _text(spec_digest, "spec digest"),
        "holder_key": _text(holder_key, "holder key"),
        "state": TicketState(state).value,
    }
    return NoetriumUnit(
        _record_id("ticket", payload),
        schemas=("resource.ticket",),
        attributes=modal_attributes(modality, {"kind": "resource.ticket", **payload}),
    )

def is_realization_ticket(value: object) -> bool:
    return type(value) is NoetriumUnit and value.attribute("kind") == "resource.ticket"


def ticket_field(ticket: NoetriumUnit, name: str):
    if not is_realization_ticket(ticket):
        raise TypeError("realization ticket projection requires resource.ticket Unit")
    value = ticket.attribute(name)
    return TicketState(value) if name == "state" else value


def physical_identity(
    provider_kind: str,
    physical_id: str,
    attributes: Mapping[str, JsonValue] | None = None,
    *,
    modality: TruthModality = TruthModality.OBSERVED,
) -> NoetriumUnit:
    payload = {
        "provider_kind": _text(provider_kind, "physical provider kind"),
        "physical_id": _text(physical_id, "physical id"),
        "attributes": _mapping(attributes),
    }
    return NoetriumUnit(
        _record_id("physical", payload),
        schemas=("resource.physical-identity",),
        attributes=modal_attributes(modality, {"kind": "resource.physical-identity", **payload}),
    )


def is_physical_identity(value: object) -> bool:
    return type(value) is NoetriumUnit and value.attribute("kind") == "resource.physical-identity"


def physical_field(identity: NoetriumUnit, name: str):
    if not is_physical_identity(identity):
        raise TypeError("physical identity projection requires resource.physical-identity Unit")
    return identity.attribute(name)


def resource_observation(
    resource_key: str,
    generation: int,
    ticket_id: str,
    spec_digest: str,
    exists: bool,
    ready: bool,
    physical: NoetriumUnit | None = None,
    observed_at_epoch_s: float | None = None,
    evidence: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    if type(exists) is not bool or type(ready) is not bool:
        raise TypeError("observation exists/ready must be boolean")
    if ready and not exists:
        raise ValueError("ready observation must exist")
    if exists != (physical is not None):
        raise ValueError("observation physical identity presence must equal exists")
    if physical is not None and not is_physical_identity(physical):
        raise TypeError("observation physical identity must be Unit")
    if observed_at_epoch_s is not None and (
        not math.isfinite(float(observed_at_epoch_s)) or float(observed_at_epoch_s) <= 0
    ):
        raise ValueError("observation time must be finite and positive")
    payload = {
        "resource_key": _text(resource_key, "observation resource"),
        "generation": _positive_generation(generation, "observation"),
        "ticket_id": _text(ticket_id, "observation ticket"),
        "spec_digest": _text(spec_digest, "observation spec digest"),
        "exists": exists,
        "ready": ready,
        "observed_at_epoch_s": observed_at_epoch_s,
        "evidence": _mapping(evidence),
    }
    roles = () if physical is None else (("physical", (physical,)),)
    return NoetriumUnit(
        _record_id("observation", {**payload, "physical": None if physical is None else physical.unit_digest}),
        schemas=("resource.observation",),
        attributes=modal_attributes(TruthModality.OBSERVED, {"kind": "resource.observation", **payload}),
        roles=roles,
    )


def is_resource_observation(value: object) -> bool:
    return type(value) is NoetriumUnit and value.attribute("kind") == "resource.observation"


def observation_field(observation: NoetriumUnit, name: str):
    if not is_resource_observation(observation):
        raise TypeError("resource observation projection requires resource.observation Unit")
    if name == "physical_identity":
        values = observation.units("physical")
        return None if not values else values[0]
    return observation.attribute(name)


def realization_binding(
    resource_key: str,
    generation: int,
    ticket_id: str,
    spec_digest: str,
    physical: NoetriumUnit,
) -> NoetriumUnit:
    if not is_physical_identity(physical):
        raise TypeError("binding physical identity must be resource.physical-identity Unit")
    payload = {
        "resource_key": _text(resource_key, "binding resource"),
        "generation": _positive_generation(generation, "binding"),
        "ticket_id": _text(ticket_id, "binding ticket"),
        "spec_digest": _text(spec_digest, "binding spec digest"),
    }
    return NoetriumUnit(
        _record_id("realization-binding", {**payload, "physical": physical.unit_digest}),
        schemas=("resource.realization-binding",),
        attributes=modal_attributes(TruthModality.AUTHORIZED, {"kind": "resource.realization-binding", **payload}),
        roles=(("physical", (physical,)),),
    )

def is_realization_binding(value: object) -> bool:
    return type(value) is NoetriumUnit and value.attribute("kind") == "resource.realization-binding"


def binding_field(binding: NoetriumUnit, name: str):
    if not is_realization_binding(binding):
        raise TypeError("realization binding projection requires resource.realization-binding Unit")
    if name == "physical_identity":
        return binding.one_unit("physical")
    return binding.attribute(name)



def resource_capacity_fact(
    dimension: str,
    limit: int,
    *,
    modality: TruthModality = TruthModality.AUTHORIZED,
) -> NoetriumUnit:
    dimension = _text(dimension, "capacity dimension")
    if type(limit) is not int or limit < 0:
        raise ValueError("capacity limit must be a non-negative integer")
    payload = {"dimension": dimension, "limit": limit}
    return NoetriumUnit(
        _record_id("capacity", payload),
        schemas=("resource.capacity",),
        attributes=modal_attributes(
            TruthModality(modality),
            {"kind": "resource.capacity", **payload},
        ),
    )


def is_resource_capacity_fact(value: object) -> bool:
    return (
        type(value) is NoetriumUnit
        and value.attribute("kind") == "resource.capacity"
    )


def capacity_field(capacity: NoetriumUnit, name: str):
    if not is_resource_capacity_fact(capacity):
        raise TypeError("resource capacity projection requires resource.capacity Unit")
    return capacity.attribute(name)


def realization_spec_fact(
    provider_kind: str,
    parameters: Mapping[str, JsonValue] | None = None,
    *,
    modality: TruthModality = TruthModality.DECLARED,
) -> NoetriumUnit:
    payload = {
        "provider_kind": _text(provider_kind, "realization provider kind"),
        "parameters": _mapping(parameters),
    }
    return NoetriumUnit(
        _record_id("realization-spec", payload),
        schemas=("resource.realization-spec",),
        attributes=modal_attributes(
            TruthModality(modality),
            {"kind": "resource.realization-spec", **payload},
        ),
    )


def is_realization_spec_fact(value: object) -> bool:
    return (
        type(value) is NoetriumUnit
        and value.attribute("kind") == "resource.realization-spec"
    )


def realization_spec_field(spec: NoetriumUnit, name: str):
    if not is_realization_spec_fact(spec):
        raise TypeError(
            "realization spec projection requires resource.realization-spec Unit"
        )
    return spec.attribute(name)

def resource_truth_modality(unit: NoetriumUnit) -> TruthModality | None:
    """Truth modality projection shared by all resource Unit schemas."""

    if type(unit) is not NoetriumUnit or not any(
        schema.startswith("resource.") for schema in unit.schemas
    ):
        raise TypeError("resource truth modality requires resource NoetriumUnit")
    return truth_modality(unit)


__all__ = [
    "TicketState",
    "resource_capacity_fact",
    "realization_spec_field",
    "realization_spec_fact",
    "is_realization_spec_fact",
    "is_resource_capacity_fact",
    "capacity_field",
    "authority_lease",
    "binding_field",
    "claim_field",
    "is_authority_lease",
    "is_physical_identity",
    "is_realization_binding",
    "is_realization_ticket",
    "is_resource_claim",
    "is_resource_observation",
    "lease_field",
    "lease_live_at",
    "observation_field",
    "physical_field",
    "physical_identity",
    "realization_binding",
    "realization_ticket",
    "resource_claim",
    "resource_observation",
    "resource_truth_modality",
    "ticket_field",
]
