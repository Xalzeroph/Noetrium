from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import JsonValue


class MinecraftCheckpointUnavailable(RuntimeError):
    """The provider cannot prove a restorable Minecraft world checkpoint."""


class MinecraftEnvironmentFailure(RuntimeError):
    """A Minecraft provider failed at a named environment phase."""

    def __init__(
        self,
        phase: str,
        message: str,
        *,
        cause_code: str = "MINECRAFT_ENVIRONMENT_FAILURE",
        diagnostics: Mapping[str, JsonValue] | None = None,
    ) -> None:
        super().__init__(f"Minecraft environment phase {phase} failed: {message}")
        self.phase = phase
        self.cause_code = cause_code
        self.diagnostics = dict(diagnostics or {})


__all__ = ["MinecraftCheckpointUnavailable", "MinecraftEnvironmentFailure"]
