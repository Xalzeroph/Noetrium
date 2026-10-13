"""Service startup readiness uses one global deadline across TCP + RCON."""
from __future__ import annotations

import time
from threading import Event
from types import SimpleNamespace

import pytest

from tests.test_minecraft_server_factory_v1 import _spec
from noetrium_platform.capabilities.environment.minecraft.composition.server_service import (
    MinecraftServerReadinessProbe, MinecraftServerServiceError,
    build_server_service_contract,
)


class _Alive:
    def alive(self, process):
        return True


class _Tcp:
    def __init__(self, delay):
        self.delay = delay

    def wait_ready(self, process, contract, backend):
        time.sleep(self.delay)
        return "tcp-ready"


class _Rcon:
    def __init__(self):
        self.calls = []

    def execute(self, command, *, timeout_s):
        self.calls.append((command, timeout_s))
        return SimpleNamespace(evidence_ref="rcon-observed")


def _contract(tmp_path, timeout):
    return build_server_service_contract(
        _spec(tmp_path), environment_digest="a" * 64,
        artifact_digest="b" * 64, runtime_identity_digest="c" * 64,
        readiness_timeout_s=timeout,
    )


def test_global_deadline_bounds_parallel_tcp_and_rcon_and_forbids_partial_success(tmp_path):
    rcon = _Rcon()
    probe = MinecraftServerReadinessProbe(
        tcp=_Tcp(.045), rcon=rcon, poll_interval_s=.001
    )
    started = time.monotonic()
    with pytest.raises(MinecraftServerServiceError, match="deadline expired"):
        probe.wait_ready(SimpleNamespace(), _contract(tmp_path, .025), _Alive())
    elapsed = time.monotonic() - started
    assert rcon.calls
    assert elapsed < .04


def test_tcp_and_rcon_attestations_start_concurrently(tmp_path):
    tcp_started = Event()
    rcon_started = Event()

    class Tcp:
        def wait_ready(self, process, contract, backend):
            del process, contract, backend
            tcp_started.set()
            assert rcon_started.wait(.2), "RCON did not overlap TCP readiness"
            return "tcp-ready"

    class Rcon:
        def execute(self, command, *, timeout_s):
            assert command == "list"
            assert timeout_s > 0
            rcon_started.set()
            assert tcp_started.wait(.2), "TCP did not overlap RCON readiness"
            return SimpleNamespace(evidence_ref="rcon-observed")

    probe = MinecraftServerReadinessProbe(
        tcp=Tcp(), rcon=Rcon(), poll_interval_s=.01
    )
    evidence = probe.wait_ready(
        SimpleNamespace(), _contract(tmp_path, .5), _Alive()
    )
    assert evidence.startswith("minecraft-server-ready:")


def test_rcon_receipt_is_still_mandatory_before_ready(tmp_path):
    rcon = _Rcon()
    probe = MinecraftServerReadinessProbe(
        tcp=_Tcp(0), rcon=rcon, poll_interval_s=.01
    )
    evidence = probe.wait_ready(
        SimpleNamespace(), _contract(tmp_path, .1), _Alive()
    )
    assert evidence.startswith("minecraft-server-ready:")
    assert len(rcon.calls) == 1
    assert rcon.calls[0][0] == "list"
    assert 0 < rcon.calls[0][1] <= .01
