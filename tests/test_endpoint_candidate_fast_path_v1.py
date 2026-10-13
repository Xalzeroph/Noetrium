from __future__ import annotations

from noetrium_platform.infrastructure.resources.authority.api import (
    AuthoritySnapshot,
    resource_claim,
    claim_field,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointProbeResult,
    EndpointProtocol,
    NetworkEndpoint,
)
from noetrium_platform.infrastructure.resources.allocation.placement import (
    automatic_endpoint_claim_candidates,
)


def _claim(claim_id: str, resource_key: str, holder_key: str, generation: int, **kwargs):
    return resource_claim(
        claim_id, resource_key, holder_key, generation,
        owner_scope=PLATFORM_SCOPE, scope_generation=1,
        scope_lease_id=None, owner_lease_id=None, **kwargs,
    )


class _Candidates:
    def __init__(self, base_port: int) -> None:
        self.base_port = base_port
        self.counts: list[int] = []

    def candidate_ports(
        self,
        *,
        host: str,
        count: int,
        protocol: EndpointProtocol,
    ) -> tuple[int, ...]:
        del host, protocol
        self.counts.append(count)
        return tuple(self.base_port + index for index in range(count))


class _Probe:
    def __init__(self) -> None:
        self.ports: list[int] = []

    def probe(self, endpoint: NetworkEndpoint) -> EndpointProbeResult:
        self.ports.append(endpoint.port)
        return EndpointProbeResult(endpoint, True, "free")


def _snapshot(*claims) -> AuthoritySnapshot:
    return AuthoritySnapshot((), tuple(claims), (), (), ())


def _allocate(
    authority: AuthoritySnapshot,
    candidates: _Candidates,
    probe: _Probe,
):
    return automatic_endpoint_claim_candidates(
        resource_key="endpoint",
        holder_key="holder",
        generation=1,
        consumer_resource_key="service",
        allocation_id="allocation",
        purpose="test",
        host="127.0.0.1",
        authority=authority,
        candidates=candidates,
        probe=probe,
        owner_scope=PLATFORM_SCOPE,
        scope_generation=1,
        scope_lease_id=None,
    )


def test_endpoint_fast_path_is_constant_after_snapshot_indexing() -> None:
    # Unrelated exclusive resources must not force N+1 socket discovery.
    authority = _snapshot(
        *(
            _claim(
                f"gpu-{index}",
                f"gpu-resource-{index}",
                "holder",
                1,
                exclusive=(f"compute:gpu:{index}",),
            )
            for index in range(128)
        )
    )
    candidates = _Candidates(41000)
    probe = _Probe()

    claims = _allocate(authority, candidates, probe)

    assert len(claims) == 1
    assert candidates.counts == [1]
    assert probe.ports == [41000]


def test_endpoint_conflict_fallback_preserves_pigeonhole_width() -> None:
    occupied = NetworkEndpoint("127.0.0.1", 42000).key
    authority = _snapshot(
        _claim(
            "endpoint-existing",
            "endpoint-existing",
            "holder",
            1,
            exclusive=(occupied,),
        ),
        _claim(
            "gpu-a",
            "gpu-a",
            "holder",
            1,
            exclusive=("compute:gpu:a",),
        ),
        _claim(
            "gpu-b",
            "gpu-b",
            "holder",
            1,
            exclusive=("compute:gpu:b",),
        ),
    )
    candidates = _Candidates(42000)
    probe = _Probe()

    claims = _allocate(authority, candidates, probe)

    assert candidates.counts == [1, authority.exclusive_token_count + 1]
    assert authority.exclusive_token_count == 3
    assert all(
        not authority.exclusive_token_claimed(claim_field(claim, "exclusive")[0])
        for claim in claims
    )
    assert tuple(claim_field(claim, "attributes")["port"] for claim in claims) == (
        42001,
        42002,
        42003,
    )
