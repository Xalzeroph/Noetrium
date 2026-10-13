from __future__ import annotations

import socket

from noetrium_platform.infrastructure.resources.allocation.api import EndpointProtocol
from noetrium_platform.infrastructure.resources.allocation.providers import local_candidates


def test_linux_listener_candidates_exclude_kernel_ephemeral_pool(monkeypatch) -> None:
    monkeypatch.setattr(
        local_candidates,
        "_linux_listener_candidate_ranges",
        lambda: ((12000, 12031), (61000, 61031)),
    )
    ports = local_candidates._discover_local_candidate_ports(
        host="127.0.0.1", count=16, protocol=EndpointProtocol.TCP
    )
    assert len(ports) == len(set(ports)) == 16
    assert all(12000 <= port <= 12031 or 61000 <= port <= 61031 for port in ports)
    assert not any(32768 <= port <= 60999 for port in ports)


def test_listener_candidates_are_physically_bindable_after_discovery(monkeypatch) -> None:
    monkeypatch.setattr(
        local_candidates,
        "_linux_listener_candidate_ranges",
        lambda: ((20000, 20127),),
    )
    ports = local_candidates._discover_local_candidate_ports(
        host="127.0.0.1", count=8, protocol=EndpointProtocol.TCP
    )
    sockets = []
    try:
        for port in ports:
            handle = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            handle.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            handle.bind(("127.0.0.1", port))
            sockets.append(handle)
    finally:
        for handle in sockets:
            handle.close()


def test_non_ephemeral_discovery_skips_occupied_listener(monkeypatch) -> None:
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    occupied.bind(("127.0.0.1", 0))
    occupied_port = int(occupied.getsockname()[1])
    try:
        low = max(1024, occupied_port - 4)
        high = min(65535, occupied_port + 4)
        monkeypatch.setattr(
            local_candidates,
            "_linux_listener_candidate_ranges",
            lambda: ((low, high),),
        )
        ports = local_candidates._discover_local_candidate_ports(
            host="127.0.0.1", count=min(4, high - low), protocol=EndpointProtocol.TCP
        )
        assert occupied_port not in ports
    finally:
        occupied.close()


def test_port_range_subtraction_respects_admin_reserved_ranges() -> None:
    assert local_candidates._subtract_port_ranges(
        ((61000, 61010), (1024, 1030)),
        ((61003, 61005), (1026, 1028)),
    ) == ((61000, 61002), (61006, 61010), (1024, 1025), (1029, 1030))


def test_candidate_range_order_is_respected_for_high_side_preference(monkeypatch) -> None:
    monkeypatch.setattr(
        local_candidates,
        "_linux_listener_candidate_ranges",
        lambda: ((65000, 65031), (12000, 12031)),
    )
    ports = local_candidates._discover_local_candidate_ports(
        host="127.0.0.1", count=8, protocol=EndpointProtocol.TCP
    )
    assert all(65000 <= port <= 65031 for port in ports)
