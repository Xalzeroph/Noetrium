from __future__ import annotations

from typing import Protocol

from .contracts import EndpointProbeResult, EndpointProtocol, NetworkEndpoint


class EndpointCandidatePortSourcePort(Protocol):
    def candidate_ports(
        self,
        *,
        host: str,
        count: int,
        protocol: EndpointProtocol = EndpointProtocol.TCP,
    ) -> tuple[int, ...]: ...


class EndpointProbePort(Protocol):
    def probe(self, endpoint: NetworkEndpoint) -> EndpointProbeResult: ...


__all__ = [
    "EndpointCandidatePortSourcePort",
    "EndpointProbePort",
]
