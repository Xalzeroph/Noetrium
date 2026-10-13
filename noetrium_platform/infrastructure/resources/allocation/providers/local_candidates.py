from __future__ import annotations

import math
import secrets
import socket
from functools import lru_cache
from pathlib import Path

from noetrium_platform.infrastructure.resources.allocation.api import EndpointProtocol


def _read_linux_port_pair(path: Path) -> tuple[int, int] | None:
    try:
        raw = path.read_text(encoding="ascii").split()
    except OSError:
        return None
    if len(raw) != 2:
        return None
    try:
        low, high = (int(value) for value in raw)
    except ValueError:
        return None
    if not 1 <= low <= high <= 65535:
        return None
    return low, high


def _read_linux_reserved_port_ranges() -> tuple[tuple[int, int], ...]:
    try:
        raw = Path("/proc/sys/net/ipv4/ip_local_reserved_ports").read_text(
            encoding="ascii"
        ).strip()
    except OSError:
        return ()
    if not raw:
        return ()
    ranges: list[tuple[int, int]] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            if "-" in token:
                low_text, high_text = token.split("-", 1)
                low, high = int(low_text), int(high_text)
            else:
                low = high = int(token)
        except ValueError:
            return ()
        if not 1 <= low <= high <= 65535:
            return ()
        ranges.append((low, high))
    return tuple(sorted(ranges))


def _subtract_port_ranges(
    bases: tuple[tuple[int, int], ...],
    excluded: tuple[tuple[int, int], ...],
) -> tuple[tuple[int, int], ...]:
    current = list(bases)
    for ex_low, ex_high in excluded:
        next_ranges: list[tuple[int, int]] = []
        for low, high in current:
            if ex_high < low or ex_low > high:
                next_ranges.append((low, high))
                continue
            if low < ex_low:
                next_ranges.append((low, ex_low - 1))
            if ex_high < high:
                next_ranges.append((ex_high + 1, high))
        current = next_ranges
    return tuple((low, high) for low, high in current if low <= high)


@lru_cache(maxsize=1)
def _linux_listener_candidate_ranges() -> tuple[tuple[int, int], ...] | None:
    """Return host-approved listener ranges outside Linux ephemeral ports."""

    # Kernel networking policy is captured once per platform process generation.
    # Re-reading procfs on every candidate would add I/O to the allocation hot path
    # without stronger ownership; a controller restart naturally refreshes the cut.
    ephemeral = _read_linux_port_pair(
        Path("/proc/sys/net/ipv4/ip_local_port_range")
    )
    if ephemeral is None:
        return None
    try:
        start = int(
            Path("/proc/sys/net/ipv4/ip_unprivileged_port_start")
            .read_text(encoding="ascii")
            .strip()
        )
    except (OSError, ValueError):
        return None
    start = max(1, min(start, 65535))
    low, high = ephemeral

    # Prefer the high-side complement: on conventional Linux policies it avoids
    # both client ephemeral traffic and the dense registered/user service region.
    # Fall back to the low-side complement only when high-side capacity is exhausted.
    bases: list[tuple[int, int]] = []
    if high < 65535:
        bases.append((max(start, high + 1), 65535))
    if start < low:
        bases.append((start, low - 1))
    bases = [(lo, hi) for lo, hi in bases if lo <= hi]
    return _subtract_port_ranges(
        tuple(bases),
        _read_linux_reserved_port_ranges(),
    )


def _permuted_range_ports(low: int, high: int):
    population = high - low + 1
    start = secrets.randbelow(population)
    if population == 1:
        stride = 1
    else:
        stride = secrets.randbelow(population - 1) + 1
        while math.gcd(stride, population) != 1:
            stride = secrets.randbelow(population - 1) + 1
    for offset in range(population):
        yield low + ((start + offset * stride) % population)


def _discover_outside_ephemeral_ports(
    *,
    host: str,
    count: int,
    protocol: EndpointProtocol,
    ranges: tuple[tuple[int, int], ...],
) -> tuple[int, ...]:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    socket_type = (
        socket.SOCK_STREAM
        if protocol is EndpointProtocol.TCP
        else socket.SOCK_DGRAM
    )
    population = sum(high - low + 1 for low, high in ranges)
    if population < count:
        raise RuntimeError(
            "kernel listener range has fewer ports than requested candidates"
        )

    sockets: list[socket.socket] = []
    ports: list[int] = []
    try:
        # Ranges are ordered by host-policy preference. Within each range, walk
        # one randomized full-cycle permutation without materializing the port
        # space. Accepted sockets stay open until the batch is complete.
        for low, high in ranges:
            for port in _permuted_range_ports(low, high):
                handle = socket.socket(family, socket_type)
                handle.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
                try:
                    handle.bind((host, port))
                except OSError:
                    handle.close()
                    continue
                sockets.append(handle)
                ports.append(port)
                if len(ports) == count:
                    return tuple(ports)
        raise RuntimeError(
            "kernel returned too few free non-ephemeral listener candidates"
        )
    finally:
        for handle in sockets:
            handle.close()


def _discover_local_candidate_ports(
    *,
    host: str = "127.0.0.1",
    count: int = 32,
    protocol: EndpointProtocol = EndpointProtocol.TCP,
) -> tuple[int, ...]:
    """Ask the kernel for currently free service-listener candidates.

    Candidate discovery is not ownership. Universal Authority admission re-probes and
    atomically fences one candidate before any service may bind it. On Linux,
    listener candidates are drawn from the complement of the kernel ephemeral
    range so the post-discovery handoff cannot race normal client-port allocation.
    """

    if not host.strip():
        raise ValueError("local endpoint candidate host is required")
    if type(count) is not int or count <= 0:
        raise ValueError("local endpoint candidate count must be positive")
    if not isinstance(protocol, EndpointProtocol):
        raise TypeError("local endpoint candidate protocol must be EndpointProtocol")

    listener_ranges = _linux_listener_candidate_ranges()
    if listener_ranges:
        return _discover_outside_ephemeral_ports(
            host=host,
            count=count,
            protocol=protocol,
            ranges=listener_ranges,
        )

    # Portable fallback when the host exposes no Linux port policy. Keep all
    # sockets open until the batch is complete to avoid duplicate discovery.
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    socket_type = (
        socket.SOCK_STREAM
        if protocol is EndpointProtocol.TCP
        else socket.SOCK_DGRAM
    )
    sockets: list[socket.socket] = []
    ports: list[int] = []
    try:
        while len(ports) < count:
            handle = socket.socket(family, socket_type)
            handle.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            handle.bind((host, 0))
            port = int(handle.getsockname()[1])
            if port in ports:
                handle.close()
                continue
            sockets.append(handle)
            ports.append(port)
        return tuple(ports)
    finally:
        for handle in sockets:
            handle.close()


class LocalEndpointCandidateSource:
    """Local-kernel candidate source owned by Resource allocation."""

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
