from __future__ import annotations

import pytest

from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftAgentSpec,
    MinecraftBranchRuntimeRequest,
    MinecraftBridgeSpec,
    MinecraftEndpointSpec,
    MinecraftEnvironmentRuntimeBinding,
    minecraft_environment_unit,
    MinecraftRconEndpoint,
    MinecraftServerSpec,
    MinecraftWorldBranch,
)
from noetrium_platform.capabilities.environment.minecraft.composition.branch_runtime import (
    MinecraftBranchRuntimeError,
    MinecraftBranchRuntimeFactory,
)
from noetrium_platform.capabilities.environment.minecraft.composition.environment import (
    MinecraftEnvironmentAssembly,
)
from noetrium_platform.capabilities.environment.minecraft.runtime import (
    MinecraftEnvironmentImplementation,
)
from noetrium_platform.foundation.scope.api import ScopeKind, scope_unit
from noetrium_platform.substrate.api import (
    NetworkEndpoint,
    ServiceProcessIdentity,
    ServiceReadyObservation,
)


class Session:
    def __init__(self, events):
        self.events = events
        self.closed = False

    def close(self):
        if not self.closed:
            self.events.append("session.close")
            self.closed = True


class EnvironmentRuntime:
    def __init__(self, events):
        self.events = events

    def open_session(self, implementation, *, session_id, services):
        self.events.append((
            "environment.open", session_id, implementation.runtime_binding.endpoint.port
        ))
        return Session(self.events)


class EnvironmentFactory:
    def __init__(self, events):
        self.events = events
        self.specs = []
        self.checkpoints = []

    def compose(self, environment, runtime_binding, *, checkpoint=None):
        self.specs.append(runtime_binding)
        self.checkpoints.append(checkpoint)
        implementation = MinecraftEnvironmentImplementation(
            environment=environment,
            runtime_binding=runtime_binding,
            bridge_factory=lambda _environment, _binding: object(),
            checkpoint=checkpoint,
        )
        return MinecraftEnvironmentAssembly(
            implementation,
            EnvironmentRuntime(self.events),
        )


class BoundServer:
    def __init__(self, events, *, fail_ready=False):
        self.events = events
        self.fail_ready = fail_ready
        self.start_calls = 0
        self.stop_calls = 0
        self.ready_calls = 0

    def start(self):
        self.start_calls += 1
        raise AssertionError("BranchRuntime must not start Authority-owned server")

    def verify_ready(self):
        self.ready_calls += 1
        self.events.append("server.ready")
        if self.fail_ready:
            raise RuntimeError("not-ready")
        return ServiceReadyObservation(
            contract_digest="c" * 64,
            process=ServiceProcessIdentity(9001, "start-9001", 9001),
            ready_evidence_ref="minecraft-ready:9001",
            ready_at=1234.5,
            evidence_refs=("provider-ready",),
        )

    def stop(self):
        self.stop_calls += 1
        raise AssertionError("BranchRuntime must not stop Authority-owned server")


class CheckpointFactory:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return object()


def _request(*, rcon=False):
    branch = MinecraftWorldBranch(
        branch_id="assignment-a",
        cut_id="fresh-world:a",
        workdir="/tmp/minecraft/assignment-a",
        level_name="research-world",
        manifest_digest="a" * 64,
        cleanup_ref="lifetime:a",
    )
    environment = minecraft_environment_unit(
        "minecraft", "test",
        agent_username="ResearchBot", agent_auth="offline", agent_version="1.21.1",
    )
    runtime_binding = MinecraftEnvironmentRuntimeBinding(
        endpoint=MinecraftEndpointSpec("127.0.0.1", None),
        bridge=MinecraftBridgeSpec(("node", "bridge.js"), "/opt/bridge"),
    )
    server = MinecraftServerSpec(
        jar_path="/assets/server.jar",
        workdir="/template",
        java_executable="/usr/bin/java",
        host="127.0.0.1",
        port=None,
        level_name="template-world",
        rcon_endpoint=MinecraftRconEndpoint() if rcon else None,
    )
    return MinecraftBranchRuntimeRequest(
        branch=branch,
        environment=environment,
        environment_runtime_template=runtime_binding,
        server_template=server,
        session_id="minecraft-session-a",
        scope=scope_unit(ScopeKind.BRANCH, "assignment-a"),
    )


def test_branch_consumes_ready_server_and_owns_only_session() -> None:
    events = []
    environment_factory = EnvironmentFactory(events)
    server = BoundServer(events)
    factory = MinecraftBranchRuntimeFactory(
        environment_factory=environment_factory,
        action_recovery_root="/state/recovery",
    )
    endpoint = NetworkEndpoint("127.0.0.1", 25566)
    binding = factory.open_bound(
        _request(),
        server=server,
        endpoint=endpoint,
    )

    assert binding.endpoint == endpoint
    assert environment_factory.specs[0].endpoint.port == 25566
    assert environment_factory.specs[0].bridge.action_recovery_root == "/state/recovery"
    session = binding.open_session(object())
    assert session is not None
    assert events == ["server.ready", ("environment.open", "minecraft-session-a", 25566)]
    assert server.start_calls == 0
    assert server.stop_calls == 0
    assert server.ready_calls == 1

    # Session reuse is local and does not re-observe/restart the physical server.
    assert binding.open_session(object()) is session
    assert server.ready_calls == 1
    binding.close()
    binding.close()
    assert events[-1] == "session.close"
    assert server.stop_calls == 0


def test_branch_binds_rcon_fact_without_owning_endpoint_lifecycle() -> None:
    events = []
    environment_factory = EnvironmentFactory(events)
    checkpoint_factory = CheckpointFactory()
    server = BoundServer(events)
    factory = MinecraftBranchRuntimeFactory(
        environment_factory=environment_factory,
        checkpoint_factory=checkpoint_factory,
    )
    endpoint = NetworkEndpoint("127.0.0.1", 25566)
    rcon = NetworkEndpoint("127.0.0.1", 25576)
    binding = factory.open_bound(
        _request(rcon=True),
        server=server,
        endpoint=endpoint,
        rcon_endpoint=rcon,
    )
    assert binding.rcon_endpoint == rcon
    assert len(checkpoint_factory.calls) == 1
    call = checkpoint_factory.calls[0]
    assert call["server"] is server
    assert call["server_spec"].port == 25566
    assert call["server_spec"].rcon_endpoint.port == 25576
    binding.open_session(object())
    assert call["readiness_evidence"].last_digest is not None
    binding.close()
    assert server.stop_calls == 0


def test_branch_rejects_rcon_shape_drift() -> None:
    factory = MinecraftBranchRuntimeFactory(
        environment_factory=EnvironmentFactory([]),
    )
    server = BoundServer([])
    with pytest.raises(ValueError, match="RCON endpoint must match"):
        factory.open_bound(
            _request(rcon=True),
            server=server,
            endpoint=NetworkEndpoint("127.0.0.1", 25566),
            rcon_endpoint=None,
        )


def test_readiness_failure_closes_session_layer_without_stopping_server() -> None:
    events = []
    server = BoundServer(events, fail_ready=True)
    factory = MinecraftBranchRuntimeFactory(
        environment_factory=EnvironmentFactory(events),
    )
    binding = factory.open_bound(
        _request(),
        server=server,
        endpoint=NetworkEndpoint("127.0.0.1", 25566),
    )
    with pytest.raises(MinecraftBranchRuntimeError, match="start failed"):
        binding.open_session(object())
    assert server.start_calls == 0
    assert server.stop_calls == 0
    with pytest.raises(MinecraftBranchRuntimeError, match="closed"):
        binding.open_session(object())
