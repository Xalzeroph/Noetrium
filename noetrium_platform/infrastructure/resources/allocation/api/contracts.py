from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EndpointProtocol(StrEnum):
    TCP = "tcp"
    UDP = "udp"


@dataclass(frozen=True, slots=True, order=True)
class NetworkEndpoint:
    host: str
    port: int
    protocol: EndpointProtocol = EndpointProtocol.TCP

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("network endpoint host is required")
        if not 1 <= self.port <= 65535:
            raise ValueError(
                "network endpoint port must be between 1 and 65535"
            )

    @property
    def key(self) -> str:
        return f"{self.protocol.value}://{self.host.casefold()}:{self.port}"


@dataclass(frozen=True, slots=True)
class EndpointProbeResult:
    endpoint: NetworkEndpoint
    available: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("endpoint probe reason is required")


__all__ = [
    "EndpointProbeResult",
    "EndpointProtocol",
    "NetworkEndpoint",
]
