from __future__ import annotations

import socket


def _discover_local_tcp_candidate_ports(
    *,
    host: str = "127.0.0.1",
    count: int = 32,
) -> tuple[int, ...]:
    """Ask the local kernel for currently free TCP port candidates.

    The returned ports are candidates, not ownership. Canonical ownership and
    fencing still belong to EndpointAllocationPort, which re-probes and leases
    each endpoint before a service may use it.
    """

    if not host.strip():
        raise ValueError("local endpoint candidate host is required")
    if type(count) is not int or count <= 0:
        raise ValueError("local endpoint candidate count must be positive")
    sockets: list[socket.socket] = []
    ports: list[int] = []
    try:
        for _ in range(count):
            handle = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            handle.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            handle.bind((host, 0))
            sockets.append(handle)
            port = int(handle.getsockname()[1])
            if port not in ports:
                ports.append(port)
        if not ports:
            raise RuntimeError("kernel returned no TCP endpoint candidates")
        return tuple(ports)
    finally:
        for handle in sockets:
            handle.close()


class LocalTcpEndpointCandidateSource:
    """Local-kernel implementation of EndpointCandidatePortSourcePort."""

    def candidate_ports(
        self,
        *,
        host: str,
        count: int,
    ) -> tuple[int, ...]:
        return _discover_local_tcp_candidate_ports(host=host, count=count)


__all__ = ["LocalTcpEndpointCandidateSource"]
