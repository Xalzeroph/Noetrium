from __future__ import annotations

import socket

from noetrium_platform.infrastructure.resources.allocation.api import EndpointProbeResult, NetworkEndpoint, EndpointProtocol


class SocketEndpointProbe:
    """Local OS fact provider for TCP/UDP endpoint availability."""

    def probe(self, endpoint: NetworkEndpoint) -> EndpointProbeResult:
        socket_type = socket.SOCK_STREAM if endpoint.protocol is EndpointProtocol.TCP else socket.SOCK_DGRAM
        sock = socket.socket(socket.AF_INET6 if ":" in endpoint.host else socket.AF_INET, socket_type)
        try:
            sock.bind((endpoint.host, endpoint.port))
        except OSError as exc:
            return EndpointProbeResult(endpoint, False, f"{type(exc).__name__}:{exc}")
        finally:
            sock.close()
        return EndpointProbeResult(endpoint, True, "bind-probe-succeeded")


__all__ = ["SocketEndpointProbe"]
