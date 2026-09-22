from __future__ import annotations

from collections.abc import Callable, Mapping

from noetrium_platform.infrastructure.lifecycle.process.api import ProcessCommandRunnerPort

from noetrium_platform.infrastructure.lifecycle.session.api import (
    PersistentSessionBackendConfig,
    PersistentSessionControlPort,
    PersistentSessionStatusConfig,
    PersistentSessionStatusProbePort,
)

from .binding import DirectoryPersistentSessionBindingStore
from .status import BoundPersistentSessionStatusProbe
from .tmux_transport import TmuxPersistentSessionControl


class UnsupportedPersistentSessionBackend(ValueError):
    pass


BackendFactory = Callable[[PersistentSessionBackendConfig], PersistentSessionControlPort]


class PersistentSessionBackendRegistry:
    """Composition registry only; backend implementations remain independent."""

    def __init__(self, factories: Mapping[str, BackendFactory]) -> None:
        self._factories = dict(factories)
        if not self._factories:
            raise ValueError("at least one persistent-session backend factory is required")

    def build_control(self, config: PersistentSessionBackendConfig) -> PersistentSessionControlPort:
        factory = self._factories.get(config.backend_id)
        if factory is None:
            raise UnsupportedPersistentSessionBackend(
                f"unsupported persistent-session backend: {config.backend_id}"
            )
        return factory(config)

    def build_status_probe(self, config: PersistentSessionStatusConfig) -> PersistentSessionStatusProbePort:
        return BoundPersistentSessionStatusProbe(
            self.build_control(config.backend),
            DirectoryPersistentSessionBindingStore(config.binding_root),
            config.session_name,
        )


def _tmux_factory(
    config: PersistentSessionBackendConfig,
    *,
    process_runner: ProcessCommandRunnerPort,
) -> PersistentSessionControlPort:
    options = config.as_dict()
    allowed = {
        "tmux_executable",
        "server_label",
        "tmpdir",
        "binary_identity_digest",
        "command_timeout_s",
    }
    unknown = sorted(set(options) - allowed)
    if unknown:
        raise ValueError(f"unknown tmux persistent-session options: {unknown}")
    timeout = float(options.get("command_timeout_s", "5.0"))
    return TmuxPersistentSessionControl(
        tmux_executable=options.get("tmux_executable", "/usr/bin/tmux"),
        server_label=options.get("server_label", "noetrium"),
        socket_directory=options.get("tmpdir", "/tmp"),
        binary_identity_digest=options.get("binary_identity_digest"),
        command_timeout_s=timeout,
        process_runner=process_runner,
    )


def default_persistent_session_backend_registry(
    process_runner: ProcessCommandRunnerPort,
) -> PersistentSessionBackendRegistry:
    return PersistentSessionBackendRegistry(
        {"tmux": lambda config: _tmux_factory(config, process_runner=process_runner)}
    )


__all__ = [
    "PersistentSessionBackendRegistry",
    "UnsupportedPersistentSessionBackend",
    "default_persistent_session_backend_registry",
]
