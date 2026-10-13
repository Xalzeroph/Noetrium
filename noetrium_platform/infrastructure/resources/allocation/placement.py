from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.resources.authority.api import (
    AuthoritySnapshot,
    claim_field,
    is_resource_claim,
    resource_claim,
)

from .api import EndpointCandidatePortSourcePort, EndpointProbePort, EndpointProtocol, NetworkEndpoint



@dataclass(frozen=True, slots=True)
class EndpointPlacement:
    """Read-only projection of one admitted endpoint claim."""

    claim_id: str
    resource_key: str
    allocation_id: str
    purpose: str
    endpoint: NetworkEndpoint
    consumer_resource_key: str

    def __post_init__(self) -> None:
        if not self.claim_id.strip() or not self.resource_key.strip():
            raise ValueError("endpoint placement Authority identity is required")
        if not self.allocation_id.strip() or not self.purpose.strip():
            raise ValueError("endpoint placement allocation identity is required")
        if not isinstance(self.endpoint, NetworkEndpoint):
            raise TypeError("endpoint placement requires NetworkEndpoint")
        if not self.consumer_resource_key.strip():
            raise ValueError("endpoint placement consumer resource is required")


def endpoint_placement_from_claim(claim: NoetriumUnit) -> EndpointPlacement:
    if not is_resource_claim(claim):
        raise TypeError("endpoint placement requires resource.claim Unit")
    attrs = dict(claim_field(claim, "attributes"))
    if attrs.get("kind") != "network-endpoint":
        raise ValueError("resource claim is not an endpoint placement")
    try:
        allocation_id = str(attrs["allocation_id"])
        purpose = str(attrs["purpose"])
        endpoint = NetworkEndpoint(
            str(attrs["host"]),
            int(attrs["port"]),
            EndpointProtocol(str(attrs["protocol"])),
        )
        consumer = str(attrs["consumer_resource_key"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("endpoint claim attributes are malformed") from exc
    return EndpointPlacement(
        claim_id=claim_field(claim, "claim_id"),
        resource_key=claim_field(claim, "resource_key"),
        allocation_id=allocation_id,
        purpose=purpose,
        endpoint=endpoint,
        consumer_resource_key=consumer,
    )


def automatic_endpoint_claim_candidates(
    *,
    resource_key: str,
    holder_key: str,
    generation: int,
    consumer_resource_key: str,
    allocation_id: str,
    purpose: str,
    host: str,
    authority: AuthoritySnapshot,
    candidates: EndpointCandidatePortSourcePort,
    probe: EndpointProbePort,
    protocol: EndpointProtocol = EndpointProtocol.TCP,
    owner_scope: NoetriumUnit,
    scope_generation: int,
    scope_lease_id: str | None,
    owner_lease_id: str | None = None,
) -> tuple[NoetriumUnit, ...]:
    """Derive enough kernel candidates from current logical contention.

    Width is not a tuning constant: with N current logical claims on the same
    host/protocol, N+1 distinct OS-free candidates guarantee at least one is not
    one of those Authority tokens. Admission still performs the linearizable
    winner selection.
    """
    if type(authority) is not AuthoritySnapshot:
        raise TypeError("automatic endpoint placement requires AuthoritySnapshot")
    # Optimistic O(1) fast path. AuthoritySnapshot indexes all active
    # exclusive tokens once, so endpoint allocation does not rescan every claim.
    first_ports = candidates.candidate_ports(
        host=host,
        count=1,
        protocol=protocol,
    )
    first_unclaimed = tuple(
        port
        for port in first_ports
        if not authority.exclusive_token_claimed(
            NetworkEndpoint(host, port, protocol).key
        )
    )
    if first_unclaimed:
        first_claims = endpoint_claim_candidates(
            resource_key=resource_key,
            holder_key=holder_key,
            generation=generation,
            consumer_resource_key=consumer_resource_key,
            allocation_id=allocation_id,
            purpose=purpose,
            host=host,
            candidate_ports=first_unclaimed,
            probe=probe,
            protocol=protocol,
            owner_scope=owner_scope,
            scope_generation=scope_generation,
            scope_lease_id=scope_lease_id,
            owner_lease_id=owner_lease_id,
        )
        if first_claims:
            return first_claims

    # Worst-case proof: endpoint claims are a subset of all active exclusive
    # tokens. Asking the kernel for T+1 mutually distinct OS-free ports, where
    # T is the total active exclusive-token count, guarantees at least one port
    # is not logically claimed by Authority (pigeonhole principle).
    fallback_ports = candidates.candidate_ports(
        host=host,
        count=authority.exclusive_token_count + 1,
        protocol=protocol,
    )
    logically_free = tuple(
        port
        for port in fallback_ports
        if not authority.exclusive_token_claimed(
            NetworkEndpoint(host, port, protocol).key
        )
    )
    return endpoint_claim_candidates(
        resource_key=resource_key,
        holder_key=holder_key,
        generation=generation,
        consumer_resource_key=consumer_resource_key,
        allocation_id=allocation_id,
        purpose=purpose,
        host=host,
        candidate_ports=logically_free,
        probe=probe,
        protocol=protocol,
        owner_scope=owner_scope,
        scope_generation=scope_generation,
        scope_lease_id=scope_lease_id,
        owner_lease_id=owner_lease_id,
    )

def endpoint_claim_candidates(
    *,
    resource_key: str,
    holder_key: str,
    generation: int,
    consumer_resource_key: str,
    allocation_id: str,
    purpose: str,
    host: str,
    candidate_ports: tuple[int, ...],
    probe: EndpointProbePort,
    protocol: EndpointProtocol = EndpointProtocol.TCP,
    owner_scope: NoetriumUnit,
    scope_generation: int,
    scope_lease_id: str | None,
    owner_lease_id: str | None = None,
) -> tuple[NoetriumUnit, ...]:
    if not resource_key.strip() or not holder_key.strip():
        raise ValueError("endpoint claim identity is required")
    if type(generation) is not int or generation < 1:
        raise ValueError("endpoint claim generation must be positive")
    if not consumer_resource_key.strip():
        raise ValueError("endpoint claim consumer resource key is required")
    if not allocation_id.strip() or not purpose.strip() or not host.strip():
        raise ValueError(
            "endpoint allocation identity, purpose and host are required"
        )
    if not isinstance(protocol, EndpointProtocol):
        raise TypeError("endpoint protocol must be EndpointProtocol")
    if type(owner_scope) is not NoetriumUnit:
        raise TypeError("endpoint claim owner_scope must be NoetriumUnit")
    if type(scope_generation) is not int or scope_generation < 1:
        raise ValueError("endpoint claim scope_generation must be positive")
    if scope_lease_id is not None and (
        type(scope_lease_id) is not str
        or not scope_lease_id.strip()
        or scope_lease_id != scope_lease_id.strip()
    ):
        raise ValueError("endpoint claim scope_lease_id must be canonical text or None")
    if owner_lease_id is not None and (
        type(owner_lease_id) is not str
        or not owner_lease_id.strip()
        or owner_lease_id != owner_lease_id.strip()
    ):
        raise ValueError("endpoint claim owner_lease_id must be canonical text or None")
    if not candidate_ports:
        raise ValueError("endpoint claim requires candidate ports")
    if len(set(candidate_ports)) != len(candidate_ports):
        raise ValueError("endpoint candidate ports must be unique")
    if any(type(port) is not int or not 1 <= port <= 65535 for port in candidate_ports):
        raise ValueError("endpoint candidate ports must be in [1, 65535]")

    claims: list[NoetriumUnit] = []
    for port in candidate_ports:
        endpoint = NetworkEndpoint(host, port, protocol)
        observation = probe.probe(endpoint)
        if observation.endpoint != endpoint:
            raise RuntimeError("endpoint probe identity drifted")
        if not observation.available:
            continue
        attributes = {
            "kind": "network-endpoint",
            "allocation_id": allocation_id,
            "purpose": purpose,
            "host": endpoint.host,
            "port": endpoint.port,
            "protocol": endpoint.protocol.value,
            "consumer_resource_key": consumer_resource_key,
        }
        if owner_lease_id is not None:
            attributes["owner_lease_id"] = owner_lease_id
        claim_id = "endpoint:" + canonical_digest(
            {
                "resource_key": resource_key,
                "generation": generation,
                "holder_key": holder_key,
                "endpoint": endpoint.key,
                "allocation_id": allocation_id,
                "owner_lease_id": owner_lease_id,
            }
        )
        claims.append(
            resource_claim(
                claim_id=claim_id,
                resource_key=resource_key,
                holder_key=holder_key,
                generation=generation,
                owner_scope=owner_scope,
                scope_generation=scope_generation,
                scope_lease_id=scope_lease_id,
                owner_lease_id=owner_lease_id,
                exclusive=(endpoint.key,),
                attributes=attributes,
            )
        )
    return tuple(claims)


__all__ = [
    "EndpointPlacement",
    "automatic_endpoint_claim_candidates",
    "endpoint_claim_candidates",
    "endpoint_placement_from_claim",
]
