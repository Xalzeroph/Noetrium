from __future__ import annotations

from dataclasses import replace
import inspect

import pytest

from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftAgentSpec,
    MinecraftBranchRuntimeRequest,
    MinecraftBridgeSpec,
    MinecraftEndpointSpec,
    MinecraftEnvironmentSpec,
    MinecraftServerSpec,
    MinecraftRconEndpoint,
    MinecraftWorldBranch,
)
from noetrium_platform.capabilities.environment.minecraft.composition import (
    MinecraftBranchRuntimeFactory,
    MinecraftEnvironmentAssembly,
)
from noetrium_platform.capabilities.environment.minecraft.runtime import MinecraftEnvironmentImplementation
from noetrium_platform.capabilities.environment.runtime.api import DurablePreparedActionSession
from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointAllocationRequest,
    EndpointAllocationState,
    EndpointProbeResult,
    NetworkEndpoint,
)
from noetrium_platform.infrastructure.resources.allocation.runtime import InMemoryEndpointAllocator
from noetrium_platform.infrastructure.resources.lease.runtime import InMemoryResourceLeaseRegistry
from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceProcessIdentity,
    ServiceReadyObservation,
    ServiceStartOutcome,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind


class AlwaysAvailableProbe:
    def probe(self, endpoint: NetworkEndpoint) -> EndpointProbeResult:
        return EndpointProbeResult(endpoint, True, "available")




class NoopGuard:
    def start(self) -> None: pass
    def assert_healthy(self) -> None: pass
    def close(self) -> None: pass


class NoopGuardFactory:
    def create(self, allocation_ids: tuple[str, ...]):
        assert allocation_ids
        return NoopGuard()


class RecordingSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def close(self) -> None:
        self.events.append("session.close")


class RecordingEnvironmentRuntime:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def open_session(self, implementation: object, *, session_id: str, services: object) -> RecordingSession:
        self.events.append(f"environment.open:{session_id}")
        return RecordingSession(self.events)


def _ready_observation(
    *,
    contract_digest: str,
    process: ServiceProcessIdentity,
    ready_evidence_ref: str,
    ready_at: float,
) -> ServiceReadyObservation:
    parameters = inspect.signature(ServiceReadyObservation).parameters
    if "ready_at" in parameters:
        return ServiceReadyObservation(
            contract_digest=contract_digest,
            process=process,
            ready_evidence_ref=ready_evidence_ref,
            ready_at=ready_at,
            evidence_refs=("ready",),
        )

    class _StandaloneReadyObservation(ServiceReadyObservation):
        __slots__ = ("ready_at",)

        def __init__(self) -> None:
            super().__init__(
                contract_digest=contract_digest,
                process=process,
                ready_evidence_ref=ready_evidence_ref,
                evidence_refs=("ready",),
            )
            object.__setattr__(self, "ready_at", ready_at)

    return _StandaloneReadyObservation()


def _start_outcome(server: "RecordingServer") -> ServiceStartOutcome:
    kwargs = {
        "contract_digest": server.contract_digest,
        "process": server.process,
        "ready_evidence_ref": server.ready_evidence_ref,
        "evidence_refs": ("start",),
    }
    if "ready_at" in inspect.signature(ServiceStartOutcome).parameters:
        kwargs["ready_at"] = server.ready_at
    return ServiceStartOutcome(**kwargs)


class RecordingServer:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.contract_digest = "c" * 64
        self.process = ServiceProcessIdentity(9001, "start-9001", 9001)
        self.ready_at = 1234.5
        self.ready_evidence_ref = "minecraft-ready:verified:9001"

    def advance_generation(self, *, pid: int, ready_at: float) -> None:
        self.process = ServiceProcessIdentity(pid, f"start-{pid}", pid)
        self.ready_at = ready_at
        self.ready_evidence_ref = f"minecraft-ready:verified:{pid}"

    def start(self) -> ServiceStartOutcome:
        self.events.append("server.start")
        return _start_outcome(self)

    def verify_ready(self) -> ServiceReadyObservation:
        self.events.append("server.ready")
        return _ready_observation(
            contract_digest=self.contract_digest,
            process=self.process,
            ready_evidence_ref=self.ready_evidence_ref,
            ready_at=self.ready_at,
        )

    def stop(self) -> None:
        self.events.append("server.stop")


def _request() -> MinecraftBranchRuntimeRequest:
    branch = MinecraftWorldBranch(
        branch_id="candidate-a",
        cut_id="cut-1",
        workdir=r"C:\mc\branches\candidate-a",
        level_name="candidate-a-world",
        manifest_digest="a" * 64,
        cleanup_ref="cleanup:candidate-a",
    )
    env = MinecraftEnvironmentSpec(
        endpoint=MinecraftEndpointSpec("127.0.0.1", 25565),
        bridge=MinecraftBridgeSpec(("node", "bridge.js"), r"C:\mc\bridge"),
        agent=MinecraftAgentSpec(username="platform_bot", version="1.20.1"),
    )
    server = MinecraftServerSpec(
        jar_path=r"C:\mc\server.jar",
        workdir=r"C:\mc\template",
        java_executable=r"C:\Java\bin\java.exe",
    )
    return MinecraftBranchRuntimeRequest(
        branch=branch,
        endpoint_allocation=EndpointAllocationRequest(
            allocation_id="candidate-a-endpoint",
            holder_scope=ScopeIdentity(ScopeKind.BRANCH, "candidate-a"),
            purpose="candidate branch server",
            host="127.0.0.1",
            candidate_ports=(25566,),
            owner_scope=PLATFORM_SCOPE,
        ),
        environment_template=env,
        server_template=server,
        session_id="candidate-a-session",
    )


def test_branch_runtime_binds_branch_endpoint_and_releases_in_reverse_order() -> None:
    leases = InMemoryResourceLeaseRegistry()
    allocations = InMemoryEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=AlwaysAvailableProbe(),
    )
    events: list[str] = []
    created_specs: list[MinecraftServerSpec] = []

    def compose_environment(spec: MinecraftEnvironmentSpec) -> MinecraftEnvironmentAssembly:
        implementation = MinecraftEnvironmentImplementation(spec=spec, bridge_factory=lambda _: object())
        return MinecraftEnvironmentAssembly(implementation, RecordingEnvironmentRuntime(events))

    class ServerFactory:
        def create(self, spec: MinecraftServerSpec, *, environment_generation: str) -> RecordingServer:
            created_specs.append(spec)
            return RecordingServer(events)

    factory = MinecraftBranchRuntimeFactory(
        endpoint_allocations=allocations,
        lease_guard_factory=NoopGuardFactory(),
        environment_factory=type("EnvironmentFactory", (), {"compose": staticmethod(compose_environment)})(),
        server_factory=ServerFactory(),
    )

    binding = factory.open(_request())
    assert binding.allocation.endpoint.port == 25566
    assert created_specs[0].port == 25566
    assert events == []

    session = binding.open_session(services=object())
    assert session is not None
    assert not isinstance(session, DurablePreparedActionSession)
    assert binding.allocation.state is EndpointAllocationState.BOUND
    assert binding.allocation.binding_evidence_ref == "minecraft-ready:verified:9001"
    assert binding.allocation.bound_at_epoch_s == 1234.5
    assert allocations.get(binding.allocation.allocation_id).state is EndpointAllocationState.BOUND
    assert created_specs[0].workdir == r"C:\mc\branches\candidate-a"
    assert created_specs[0].level_name == "candidate-a-world"
    binding.close()

    assert events == [
        "server.start",
        "server.ready",
        "environment.open:candidate-a-session",
        "session.close",
        "server.stop",
    ]
    assert not allocations.active()


def test_branch_runtime_rebinds_new_server_generation_with_prior_proof_cas() -> None:
    leases = InMemoryResourceLeaseRegistry()
    delegate = InMemoryEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=AlwaysAvailableProbe(),
    )

    class GenerationAwareAllocator:
        def __init__(self) -> None:
            self.replacements: list[tuple[str, str]] = []

        def __getattr__(self, name):
            return getattr(delegate, name)

        def replace_bound(self, proof, *, expected_previous_binding_proof_digest: str):
            current = delegate.get(proof.allocation_id)
            assert current.binding_proof_digest == expected_previous_binding_proof_digest
            updated = replace(
                current,
                binding_proof_digest=proof.digest(),
                binding_evidence_ref=proof.evidence_ref,
                bound_at_epoch_s=proof.observed_at_epoch_s,
            )
            delegate._allocations[proof.allocation_id] = updated
            self.replacements.append(
                (expected_previous_binding_proof_digest, proof.digest())
            )
            return updated

    allocations = GenerationAwareAllocator()
    events: list[str] = []
    servers: list[RecordingServer] = []

    def compose_environment(spec: MinecraftEnvironmentSpec) -> MinecraftEnvironmentAssembly:
        implementation = MinecraftEnvironmentImplementation(
            spec=spec, bridge_factory=lambda _: object()
        )
        return MinecraftEnvironmentAssembly(
            implementation, RecordingEnvironmentRuntime(events)
        )

    class ServerFactory:
        def create(self, spec: MinecraftServerSpec, *, environment_generation: str) -> RecordingServer:
            server = RecordingServer(events)
            servers.append(server)
            return server

    factory = MinecraftBranchRuntimeFactory(
        endpoint_allocations=allocations,
        lease_guard_factory=NoopGuardFactory(),
        environment_factory=type(
            "EnvironmentFactory", (), {"compose": staticmethod(compose_environment)}
        )(),
        server_factory=ServerFactory(),
    )
    binding = factory.open(_request())
    binding.open_session(services=object())
    previous = binding.allocation.binding_proof_digest
    assert previous is not None

    server = servers[0]
    server.advance_generation(pid=9002, ready_at=2345.5)
    readiness = server.verify_ready()
    binding._confirm_bound_endpoints(readiness)

    assert len(allocations.replacements) == 1
    assert allocations.replacements[0][0] == previous
    assert binding.allocation.binding_proof_digest == allocations.replacements[0][1]
    assert binding.allocation.binding_proof_digest != previous
    assert binding.allocation.binding_evidence_ref == "minecraft-ready:verified:9002"
    assert binding.allocation.bound_at_epoch_s == 2345.5

    # Exact replay of the same READY generation is idempotent, not a CAS replace.
    binding._confirm_bound_endpoints(readiness)
    assert len(allocations.replacements) == 1
    binding.close()
    assert not delegate.active()


def test_branch_runtime_fails_closed_without_authoritative_ready_at() -> None:
    leases = InMemoryResourceLeaseRegistry()
    allocations = InMemoryEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=AlwaysAvailableProbe(),
    )
    events: list[str] = []

    def compose_environment(spec: MinecraftEnvironmentSpec) -> MinecraftEnvironmentAssembly:
        implementation = MinecraftEnvironmentImplementation(
            spec=spec, bridge_factory=lambda _: object()
        )
        return MinecraftEnvironmentAssembly(
            implementation, RecordingEnvironmentRuntime(events)
        )

    class MissingReadyAtServer(RecordingServer):
        def verify_ready(self):
            self.events.append("server.ready")
            class MissingReadyAt:
                contract_digest = self.contract_digest
                process = self.process
                ready_evidence_ref = self.ready_evidence_ref
            return MissingReadyAt()

    class ServerFactory:
        def create(self, spec: MinecraftServerSpec, *, environment_generation: str):
            return MissingReadyAtServer(events)

    factory = MinecraftBranchRuntimeFactory(
        endpoint_allocations=allocations,
        lease_guard_factory=NoopGuardFactory(),
        environment_factory=type(
            "EnvironmentFactory", (), {"compose": staticmethod(compose_environment)}
        )(),
        server_factory=ServerFactory(),
    )
    binding = factory.open(_request())
    with pytest.raises(Exception, match="branch runtime start failed") as raised:
        binding.open_session(services=object())
    assert raised.value.phase == "start"
    assert raised.value.cause is not None
    assert raised.value.cause.phase == "bind"
    assert "typed ServiceReadyObservation" in str(raised.value.cause)
    assert not allocations.active()


def test_branch_runtime_rebinds_game_and_rcon_generation_together() -> None:
    leases = InMemoryResourceLeaseRegistry()
    delegate = InMemoryEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=AlwaysAvailableProbe(),
    )

    class GenerationAwareAllocator:
        def __init__(self) -> None:
            self.replaced: list[str] = []
        def __getattr__(self, name):
            return getattr(delegate, name)
        def replace_bound(self, proof, *, expected_previous_binding_proof_digest: str):
            current = delegate.get(proof.allocation_id)
            assert current.binding_proof_digest == expected_previous_binding_proof_digest
            updated = replace(
                current,
                binding_proof_digest=proof.digest(),
                binding_evidence_ref=proof.evidence_ref,
                bound_at_epoch_s=proof.observed_at_epoch_s,
            )
            delegate._allocations[proof.allocation_id] = updated
            self.replaced.append(proof.allocation_id)
            return updated

    allocations = GenerationAwareAllocator()
    events: list[str] = []
    servers: list[RecordingServer] = []

    def compose_environment(spec: MinecraftEnvironmentSpec) -> MinecraftEnvironmentAssembly:
        implementation = MinecraftEnvironmentImplementation(
            spec=spec, bridge_factory=lambda _: object()
        )
        return MinecraftEnvironmentAssembly(
            implementation, RecordingEnvironmentRuntime(events)
        )

    class ServerFactory:
        def create(self, spec: MinecraftServerSpec, *, environment_generation: str):
            server = RecordingServer(events)
            servers.append(server)
            return server

    request = _request()
    request = replace(
        request,
        server_template=replace(
            request.server_template,
            rcon_endpoint=MinecraftRconEndpoint(port=25575),
        ),
        rcon_endpoint_allocation=EndpointAllocationRequest(
            allocation_id="candidate-a-rcon-generation",
            holder_scope=ScopeIdentity(ScopeKind.BRANCH, "candidate-a"),
            purpose="candidate branch rcon generation",
            host="127.0.0.1",
            candidate_ports=(25578,),
            owner_scope=PLATFORM_SCOPE,
        ),
    )
    factory = MinecraftBranchRuntimeFactory(
        endpoint_allocations=allocations,
        lease_guard_factory=NoopGuardFactory(),
        environment_factory=type(
            "EnvironmentFactory", (), {"compose": staticmethod(compose_environment)}
        )(),
        server_factory=ServerFactory(),
    )
    binding = factory.open(request)
    binding.open_session(services=object())
    server = servers[0]
    server.advance_generation(pid=9003, ready_at=3456.5)
    binding._confirm_bound_endpoints(server.verify_ready())

    assert allocations.replaced == [
        "candidate-a-endpoint",
        "candidate-a-rcon-generation",
    ]
    assert binding.allocation.bound_at_epoch_s == 3456.5
    assert binding.rcon_allocation is not None
    assert binding.rcon_allocation.bound_at_epoch_s == 3456.5
    binding.close()
    assert not delegate.active()


def test_branch_runtime_binds_recovery_root_outside_world_and_preserves_prepared_capability() -> None:
    leases = InMemoryResourceLeaseRegistry()
    allocations = InMemoryEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=AlwaysAvailableProbe(),
    )
    events: list[str] = []
    composed_specs: list[MinecraftEnvironmentSpec] = []

    class PreparedSession(RecordingSession):
        action_recovery_durability = "crash_durable"

        def prepare_action_recovery(self, request, context):
            self.events.append("session.prepare")
            return (request, context)

        def execute_prepared_action(self, request, handle):
            self.events.append("session.execute")
            return (request, handle)

        def reconcile_prepared_action(self, handle, context):
            self.events.append("session.reconcile-prepared")
            return (handle, context)

    class PreparedRuntime(RecordingEnvironmentRuntime):
        def open_session(self, implementation: object, *, session_id: str, services: object):
            self.events.append(f"environment.open:{session_id}")
            return PreparedSession(self.events)

    def compose_environment(spec: MinecraftEnvironmentSpec) -> MinecraftEnvironmentAssembly:
        composed_specs.append(spec)
        implementation = MinecraftEnvironmentImplementation(spec=spec, bridge_factory=lambda _: object())
        return MinecraftEnvironmentAssembly(implementation, PreparedRuntime(events))

    class ServerFactory:
        def create(self, spec: MinecraftServerSpec, *, environment_generation: str) -> RecordingServer:
            return RecordingServer(events)

    recovery_root = r"C:\mc\branches\.action-recovery"
    factory = MinecraftBranchRuntimeFactory(
        endpoint_allocations=allocations,
        lease_guard_factory=NoopGuardFactory(),
        environment_factory=type("EnvironmentFactory", (), {"compose": staticmethod(compose_environment)})(),
        server_factory=ServerFactory(),
        action_recovery_root=recovery_root,
    )

    binding = factory.open(_request())
    assert composed_specs[0].bridge.action_recovery_root == recovery_root
    assert not recovery_root.startswith(_request().branch.workdir + "\\")
    session = binding.open_session(services=object())
    assert isinstance(session, DurablePreparedActionSession)
    assert session.action_recovery_durability == "crash_durable"
    assert session.prepare_action_recovery("request", "context") == ("request", "context")
    assert session.execute_prepared_action("request", "handle") == ("request", "handle")
    assert session.reconcile_prepared_action("handle", "context") == ("handle", "context")
    binding.close()
    assert "session.prepare" in events
    assert "session.execute" in events
    assert "session.reconcile-prepared" in events
    assert not allocations.active()


def test_branch_runtime_releases_endpoint_when_server_start_fails() -> None:
    leases = InMemoryResourceLeaseRegistry()
    allocations = InMemoryEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=AlwaysAvailableProbe(),
    )
    events: list[str] = []

    class FailingServer(RecordingServer):
        def start(self) -> None:
            events.append("server.start")
            raise RuntimeError("server failed")

    def compose_environment(spec: MinecraftEnvironmentSpec) -> MinecraftEnvironmentAssembly:
        return MinecraftEnvironmentAssembly(
            MinecraftEnvironmentImplementation(spec=spec, bridge_factory=lambda _: object()),
            RecordingEnvironmentRuntime(events),
        )

    class ServerFactory:
        def create(self, spec: MinecraftServerSpec, *, environment_generation: str) -> FailingServer:
            return FailingServer(events)

    factory = MinecraftBranchRuntimeFactory(
        endpoint_allocations=allocations,
        lease_guard_factory=NoopGuardFactory(),
        environment_factory=type("EnvironmentFactory", (), {"compose": staticmethod(compose_environment)})(),
        server_factory=ServerFactory(),
    )
    binding = factory.open(_request())

    try:
        binding.open_session(services=object())
    except RuntimeError:
        pass
    else:
        raise AssertionError("server start failure must propagate")

    assert events == ["server.start", "server.stop"]
    assert not allocations.active()


def test_branch_runtime_allocates_and_rebinds_rcon_endpoint_as_part_of_branch_transaction() -> None:
    leases = InMemoryResourceLeaseRegistry()
    allocations = InMemoryEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=AlwaysAvailableProbe(),
    )
    events: list[str] = []
    created_specs: list[MinecraftServerSpec] = []

    def compose_environment(spec: MinecraftEnvironmentSpec) -> MinecraftEnvironmentAssembly:
        return MinecraftEnvironmentAssembly(
            MinecraftEnvironmentImplementation(spec=spec, bridge_factory=lambda _: object()),
            RecordingEnvironmentRuntime(events),
        )

    class ServerFactory:
        def create(self, spec: MinecraftServerSpec, *, environment_generation: str) -> RecordingServer:
            created_specs.append(spec)
            return RecordingServer(events)

    factory = MinecraftBranchRuntimeFactory(
        endpoint_allocations=allocations,
        lease_guard_factory=NoopGuardFactory(),
        environment_factory=type("EnvironmentFactory", (), {"compose": staticmethod(compose_environment)})(),
        server_factory=ServerFactory(),
    )
    request = _request()
    request = replace(
        request,
        server_template=replace(request.server_template, rcon_endpoint=MinecraftRconEndpoint(port=25575)),
        rcon_endpoint_allocation=EndpointAllocationRequest(
            allocation_id="candidate-a-rcon",
            holder_scope=ScopeIdentity(ScopeKind.BRANCH, "candidate-a"),
            purpose="candidate branch rcon",
            host="127.0.0.1",
            candidate_ports=(25576,),
            owner_scope=PLATFORM_SCOPE,
        ),
    )

    binding = factory.open(request)
    assert binding.rcon_allocation is not None
    assert binding.rcon_allocation.endpoint.port == 25576
    assert created_specs[0].rcon_endpoint is not None
    assert created_specs[0].rcon_endpoint.port == 25576
    binding.open_session(services=object())
    assert binding.allocation.state is EndpointAllocationState.BOUND
    assert binding.rcon_allocation is not None
    assert binding.rcon_allocation.state is EndpointAllocationState.BOUND
    assert binding.allocation.binding_evidence_ref == "minecraft-ready:verified:9001"
    assert binding.rcon_allocation.binding_evidence_ref == "minecraft-ready:verified:9001"
    binding.close()
    assert not allocations.active()


def test_branch_runtime_releases_all_endpoints_when_binding_confirmation_fails() -> None:
    leases = InMemoryResourceLeaseRegistry()
    delegate = InMemoryEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=AlwaysAvailableProbe(),
    )

    class FailingSecondConfirmation:
        def __init__(self) -> None:
            self.confirmations = 0

        def __getattr__(self, name):
            return getattr(delegate, name)

        def confirm_bound(self, proof):
            self.confirmations += 1
            if self.confirmations == 2:
                raise RuntimeError("simulated RCON binding proof rejection")
            return delegate.confirm_bound(proof)

    allocations = FailingSecondConfirmation()
    events: list[str] = []

    def compose_environment(spec: MinecraftEnvironmentSpec) -> MinecraftEnvironmentAssembly:
        return MinecraftEnvironmentAssembly(
            MinecraftEnvironmentImplementation(spec=spec, bridge_factory=lambda _: object()),
            RecordingEnvironmentRuntime(events),
        )

    class ServerFactory:
        def create(self, spec: MinecraftServerSpec, *, environment_generation: str) -> RecordingServer:
            return RecordingServer(events)

    request = _request()
    request = replace(
        request,
        server_template=replace(request.server_template, rcon_endpoint=MinecraftRconEndpoint(port=25575)),
        rcon_endpoint_allocation=EndpointAllocationRequest(
            allocation_id="candidate-a-rcon-failing",
            holder_scope=ScopeIdentity(ScopeKind.BRANCH, "candidate-a"),
            purpose="candidate branch rcon",
            host="127.0.0.1",
            candidate_ports=(25577,),
            owner_scope=PLATFORM_SCOPE,
        ),
    )
    factory = MinecraftBranchRuntimeFactory(
        endpoint_allocations=allocations,
        lease_guard_factory=NoopGuardFactory(),
        environment_factory=type("EnvironmentFactory", (), {"compose": staticmethod(compose_environment)})(),
        server_factory=ServerFactory(),
    )
    binding = factory.open(request)

    with pytest.raises(Exception, match="branch runtime start failed"):
        binding.open_session(services=object())

    assert allocations.confirmations == 2
    assert events == ["server.start", "server.ready", "server.stop"]
    assert not delegate.active()


def test_branch_runtime_rejects_rcon_template_without_rcon_allocation() -> None:
    request = _request()
    with pytest.raises(ValueError, match="RCON template and allocation"):
        replace(request, server_template=replace(request.server_template, rcon_endpoint=MinecraftRconEndpoint()))


def test_branch_session_surfaces_endpoint_lease_guard_failure() -> None:
    leases = InMemoryResourceLeaseRegistry()
    allocations = InMemoryEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=AlwaysAvailableProbe(),
    )
    events: list[str] = []

    class SessionWithObserve(RecordingSession):
        def observe(self, context):
            self.events.append("session.observe")
            return object()

    class RuntimeWithObserve(RecordingEnvironmentRuntime):
        def open_session(self, implementation: object, *, session_id: str, services: object):
            self.events.append(f"environment.open:{session_id}")
            return SessionWithObserve(self.events)

    def compose_environment(spec: MinecraftEnvironmentSpec) -> MinecraftEnvironmentAssembly:
        return MinecraftEnvironmentAssembly(
            MinecraftEnvironmentImplementation(spec=spec, bridge_factory=lambda _: object()),
            RuntimeWithObserve(events),
        )

    class ServerFactory:
        def create(self, spec: MinecraftServerSpec, *, environment_generation: str) -> RecordingServer:
            return RecordingServer(events)

    class Guard:
        def __init__(self) -> None:
            self.failed = False
        def start(self) -> None:
            return None
        def assert_healthy(self) -> None:
            if self.failed:
                raise RuntimeError("lease guard lost")
        def close(self) -> None:
            return None

    guard = Guard()

    class GuardFactory:
        def create(self, allocation_ids: tuple[str, ...]):
            assert allocation_ids == ("candidate-a-endpoint",)
            return guard

    factory = MinecraftBranchRuntimeFactory(
        endpoint_allocations=allocations,
        environment_factory=type("EnvironmentFactory", (), {"compose": staticmethod(compose_environment)})(),
        server_factory=ServerFactory(),
        lease_guard_factory=GuardFactory(),
    )
    binding = factory.open(_request())
    session = binding.open_session(services=object())
    guard.failed = True
    with pytest.raises(RuntimeError, match="lease guard lost"):
        session.observe(object())
    binding.close()
    assert not allocations.active()
