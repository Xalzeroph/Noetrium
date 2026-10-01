from __future__ import annotations

from collections.abc import Callable, Mapping
import json

from noetrium_platform.infrastructure.lifecycle.process.api import ProcessCommandRunnerPort

from noetrium_platform.infrastructure.lifecycle.session.api import (
    PersistentSessionBackendConfig,
    PersistentSessionControlPort,
    PersistentSessionStatusConfig,
    PersistentSessionStatusProbePort,
)

from .binding import DirectoryPersistentSessionBindingStore
from .docker_transport import DockerPersistentSessionControl
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


def _tuple_json_option(options: dict[str, str], key: str) -> tuple[str, ...]:
    raw = options.get(key, "[]")
    value = json.loads(raw)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{key} must be a JSON list of non-empty strings")
    return tuple(value)


def _docker_factory(
    config: PersistentSessionBackendConfig,
    *,
    process_runner: ProcessCommandRunnerPort,
) -> PersistentSessionControlPort:
    options = config.as_dict()
    allowed = {
        "docker_executable", "image", "user", "network_host", "gpus",
        "mounts_json", "group_add_json", "restart_policy",
        "binary_identity_digest", "image_identity", "daemon_identity",
        "command_timeout_s",
    }
    unknown = sorted(set(options) - allowed)
    if unknown:
        raise ValueError(f"unknown Docker persistent-session options: {unknown}")
    image = options.get("image", "").strip()
    if not image:
        raise ValueError("Docker persistent-session backend requires image")
    network_raw = options.get("network_host", "true").strip().lower()
    if network_raw not in {"true", "false"}:
        raise ValueError("network_host must be true or false")
    return DockerPersistentSessionControl(
        process_runner=process_runner,
        image=image,
        docker_executable=options.get("docker_executable", "docker"),
        command_timeout_s=float(options.get("command_timeout_s", "10.0")),
        user=options.get("user"),
        network_host=network_raw == "true",
        gpus=options.get("gpus"),
        mounts=_tuple_json_option(options, "mounts_json"),
        group_add=_tuple_json_option(options, "group_add_json"),
        restart_policy=options.get("restart_policy", "unless-stopped"),
        binary_identity_digest=options.get("binary_identity_digest"),
        image_identity=options.get("image_identity"),
        daemon_identity=options.get("daemon_identity"),
    )


def default_persistent_session_backend_registry(
    process_runner: ProcessCommandRunnerPort,
) -> PersistentSessionBackendRegistry:
    return PersistentSessionBackendRegistry(
        {
            "tmux": lambda config: _tmux_factory(
                config, process_runner=process_runner
            ),
            "docker": lambda config: _docker_factory(
                config, process_runner=process_runner
            ),
        }
    )


__all__ = [
    "PersistentSessionBackendRegistry",
    "UnsupportedPersistentSessionBackend",
    "default_persistent_session_backend_registry",
]
