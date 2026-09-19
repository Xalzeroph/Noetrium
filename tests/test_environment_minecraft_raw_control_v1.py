from __future__ import annotations

from noetrium_platform.capabilities.environment.api import ActionRequest
from noetrium_platform.capabilities.environment.category.api import (
    EnvironmentCategoryStatus,
)
from noetrium_platform.capabilities.environment.category.runtime.catalog import (
    canonical_environment_implementations,
)
from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftRawControlCommand,
    MinecraftRawControlObservation,
)
from noetrium_platform.capabilities.environment.minecraft.providers import (
    MinecraftRawControlProvider,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_digest,
)


class _Backend:
    def __init__(self) -> None:
        self.closed = False
        self.commands = []

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "backend": "minecraft-raw-control-test",
            "implementation_revision": 1,
        })

    def reset(self, *, session_id, context):
        assert session_id == "episode-1"
        assert context.run_id == "run"
        return MinecraftRawControlObservation(
            frame_artifact_ref="sha256:frame0",
            state={"inventory": {}},
        )

    def step(self, command, *, context):
        assert isinstance(command, MinecraftRawControlCommand)
        assert context.task_id == "look-at-sky"
        self.commands.append(command)
        return MinecraftRawControlObservation(
            frame_artifact_ref="sha256:frame1",
            state={"inventory": {}, "isGuiOpen": False},
            reward=1.0,
            success=True,
            terminated=True,
            receipt={"command_digest": command.command_digest},
        )

    def close(self):
        self.closed = True


def _context() -> ExecutionContext:
    return ExecutionContext(
        "run",
        "trace",
        "span",
        task_id="look-at-sky",
    )


def test_minecraft_raw_control_surface_is_catalogued_available() -> None:
    descriptor = next(
        row
        for row in canonical_environment_implementations()
        if row.implementation_id == "minecraft.raw_control"
    )
    assert descriptor.status is EnvironmentCategoryStatus.AVAILABLE
    assert descriptor.backend_kind == "raw_pixel_keyboard_mouse"


def test_minecraft_raw_control_provider_preserves_low_level_controls() -> None:
    backend = _Backend()
    provider = MinecraftRawControlProvider(backend=backend)
    session = provider.open_session(
        session_id="episode-1",
        services=object(),
    )

    initial = session.observe(_context())
    assert initial.payload["frame_artifact_ref"] == "sha256:frame0"
    assert initial.payload["done"] is False

    controls = {
        "buttons": {
            "forward": 1,
            "jump": 0,
            "inventory": 0,
        },
        "camera": [0.25, -0.5],
    }
    request = ActionRequest(
        "control-1",
        MinecraftRawControlProvider.ACTION_TYPE,
        {"controls": controls},
        _context(),
    )
    result = session.act(request)

    assert result.accepted is True
    assert result.observation is not None
    assert result.observation.payload["frame_artifact_ref"] == "sha256:frame1"
    assert result.observation.payload["reward"] == 1.0
    assert result.observation.payload["success"] is True
    assert result.observation.payload["done"] is True
    assert backend.commands[0].controls == controls
    assert result.effect is not None
    assert session.reconcile(result.effect, _context()) == result.effect

    session.close()
    assert backend.closed is True
