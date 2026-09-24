from __future__ import annotations

import socket

from noetrium_platform.infrastructure.resources.allocation.api import EndpointProtocol


def _discover_local_candidate_ports(
    *,
    host: str = "127.0.0.1",
    count: int = 32,
    protocol: EndpointProtocol = EndpointProtocol.TCP,
) -> tuple[int, ...]:
    """Ask the local kernel for free endpoint candidates.

    Returned ports are non-authoritative hints. The allocation authority
    re-probes and atomically fences the selected endpoint.
    """

    if not host.strip():
        raise ValueError("local endpoint candidate host is required")
    if type(count) is not int or count <= 0:
        raise ValueError("local endpoint candidate count must be positive")
    if type(protocol) is not EndpointProtocol:
        raise TypeError("endpoint candidate protocol must be EndpointProtocol")
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    socket_type = (
        socket.SOCK_STREAM
        if protocol is EndpointProtocol.TCP
        else socket.SOCK_DGRAM
    )
    sockets: list[socket.socket] = []
    ports: list[int] = []
    try:
        for _ in range(count):
            handle = socket.socket(family, socket_type)
            handle.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            handle.bind((host, 0))
            sockets.append(handle)
            port = int(handle.getsockname()[1])
            if port not in ports:
                ports.append(port)
        if not ports:
            raise RuntimeError("kernel returned no endpoint candidates")
        return tuple(ports)
    finally:
        for handle in sockets:
            handle.close()


class LocalEndpointCandidateSource:
    def candidate_ports(
        self,
        *,
        host: str,
        count: int,
        protocol: EndpointProtocol = EndpointProtocol.TCP,
    ) -> tuple[int, ...]:
        return _discover_local_candidate_ports(
            host=host,
            count=count,
            protocol=protocol,
        )


__all__ = ["LocalEndpointCandidateSource"]
