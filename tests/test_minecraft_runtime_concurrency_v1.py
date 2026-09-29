from __future__ import annotations

from types import SimpleNamespace
from threading import Event, RLock, Thread

from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftAgentSpec,
    MinecraftBridgeSpec,
    MinecraftEndpointSpec,
)
from noetrium_platform.capabilities.environment.minecraft.providers.jsonl_bridge import (
    JsonlMinecraftBridge,
)
from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    LocalMinecraftLifetimeSessionAuthority,
)
from noetrium_platform.infrastructure.lifecycle.host.providers import LocalOperatingSystemRoute


class _RejectSerialTaskGroup:
    def open_serial_actor(self, *args, **kwargs):
        raise AssertionError("Minecraft bridge must not occupy a SERIAL worker")


class _HealthyGuard:
    def assert_healthy(self) -> None:
        return None


def test_minecraft_bridge_constructor_does_not_allocate_serial_actor() -> None:
    JsonlMinecraftBridge(
        endpoint=MinecraftEndpointSpec(port=25565),
        spec=MinecraftBridgeSpec(command=("node",), cwd="."),
        agent=MinecraftAgentSpec(version="1.21.1"),
        operating_system=LocalOperatingSystemRoute(),
        process_supervisor=object(),
        task_group=_RejectSerialTaskGroup(),
    )


def test_minecraft_lifetime_open_is_single_flight_per_lifetime_not_global() -> None:
    authority = object.__new__(LocalMinecraftLifetimeSessionAuthority)
    authority.lock = RLock()
    authority.runtimes = {}
    authority._lifetime_locks = {}

    first_open_started = Event()
    release_first = Event()
    results: dict[str, object] = {}

    def fake_open(context):
        if context.lifetime_id == "lifetime-a":
            first_open_started.set()
            assert release_first.wait(2.0)
        return SimpleNamespace(
            session=f"session:{context.lifetime_id}",
            instance_guard=_HealthyGuard(),
        )

    authority._open = fake_open

    def acquire(name: str) -> None:
        results[name] = authority.session_for(SimpleNamespace(lifetime_id=name))

    first = Thread(target=acquire, args=("lifetime-a",))
    first.start()
    assert first_open_started.wait(1.0)

    second = Thread(target=acquire, args=("lifetime-b",))
    second.start()
    second.join(0.5)
    assert not second.is_alive(), "unrelated lifetime was serialized behind physical open"
    assert results["lifetime-b"] == "session:lifetime-b"

    release_first.set()
    first.join(1.0)
    assert not first.is_alive()
    assert results["lifetime-a"] == "session:lifetime-a"
