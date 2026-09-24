from __future__ import annotations

from dataclasses import dataclass
import json
from time import monotonic, sleep
from typing import Mapping, Protocol

from noetrium_platform.substrate.api import LocalCommandRunnerPort


MANAGED_CONTAINER_LABEL = "io.noetrium.managed"
MANAGED_CONTAINER_LABEL_VALUE = "leased-container-v1"


class DockerContainerRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DockerContainerObservation:
    container_id: str
    name: str
    image: str
    running: bool
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.container_id.strip() or not self.name.strip() or not self.image.strip():
            raise ValueError("Docker container observation identity is incomplete")


class DockerManagedContainerPort(Protocol):
    def inspect(self, reference: str) -> DockerContainerObservation | None: ...
    def list_managed(self) -> tuple[DockerContainerObservation, ...]: ...
    def wait_running(
        self, reference: str, *, timeout_seconds: float = 10.0
    ) -> DockerContainerObservation: ...
    def remove(self, reference: str, *, force: bool = True) -> None: ...


class DockerCliManagedContainerProvider:
    """Observe/remove only explicitly Noetrium-labelled Docker containers."""

    def __init__(
        self,
        runner: LocalCommandRunnerPort,
        *,
        docker_executable: str = "docker",
        command_timeout_seconds: float = 15.0,
    ) -> None:
        if not docker_executable.strip():
            raise ValueError("docker executable is required")
        if command_timeout_seconds <= 0:
            raise ValueError("Docker command timeout must be positive")
        self._runner = runner
        self._docker = docker_executable
        self._timeout = float(command_timeout_seconds)

    @staticmethod
    def _missing(stderr: str) -> bool:
        lowered = stderr.casefold()
        return "no such object" in lowered or "no such container" in lowered

    @staticmethod
    def _decode_inspect(stdout: str) -> DockerContainerObservation:
        try:
            payload = json.loads(stdout)
            row = payload[0]
            config = row["Config"]
            state = row["State"]
        except (json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
            raise DockerContainerRuntimeError(
                "Docker inspect returned malformed container state"
            ) from exc
        labels = config.get("Labels") or {}
        if not isinstance(labels, dict):
            raise DockerContainerRuntimeError("Docker inspect labels are not an object")
        return DockerContainerObservation(
            str(row["Id"]),
            str(row["Name"]).lstrip("/"),
            str(config["Image"]),
            bool(state["Running"]),
            {str(key): str(value) for key, value in labels.items()},
        )

    def inspect(self, reference: str) -> DockerContainerObservation | None:
        if not reference.strip():
            raise ValueError("Docker container reference is required")
        result = self._runner.run(
            (self._docker, "inspect", reference),
            timeout_seconds=self._timeout,
        )
        if result.returncode != 0:
            if self._missing(result.stderr):
                return None
            raise DockerContainerRuntimeError(
                f"Docker inspect failed with exit code {result.returncode}"
            )
        return self._decode_inspect(result.stdout)

    def list_managed(self) -> tuple[DockerContainerObservation, ...]:
        result = self._runner.run(
            (
                self._docker,
                "ps",
                "-aq",
                "--filter",
                f"label={MANAGED_CONTAINER_LABEL}={MANAGED_CONTAINER_LABEL_VALUE}",
            ),
            timeout_seconds=self._timeout,
        )
        if result.returncode != 0:
            raise DockerContainerRuntimeError(
                f"Docker managed-container listing failed with exit code {result.returncode}"
            )
        rows: list[DockerContainerObservation] = []
        for container_id in (
            line.strip() for line in result.stdout.splitlines() if line.strip()
        ):
            observed = self.inspect(container_id)
            if observed is not None:
                rows.append(observed)
        return tuple(sorted(rows, key=lambda row: row.container_id))

    def wait_running(
        self,
        reference: str,
        *,
        timeout_seconds: float = 10.0,
    ) -> DockerContainerObservation:
        if timeout_seconds <= 0:
            raise ValueError("Docker running wait timeout must be positive")
        deadline = monotonic() + timeout_seconds
        last: DockerContainerObservation | None = None
        while monotonic() < deadline:
            last = self.inspect(reference)
            if last is not None and last.running:
                return last
            sleep(0.05)
        state = "missing" if last is None else "not-running"
        raise DockerContainerRuntimeError(
            f"Docker container did not become running before timeout: {state}"
        )

    def remove(self, reference: str, *, force: bool = True) -> None:
        observed = self.inspect(reference)
        if observed is None:
            return
        argv = [self._docker, "rm"]
        if force:
            argv.append("-f")
        argv.append(observed.container_id)
        result = self._runner.run(tuple(argv), timeout_seconds=self._timeout)
        if result.returncode != 0 and not self._missing(result.stderr):
            raise DockerContainerRuntimeError(
                f"Docker container removal failed with exit code {result.returncode}"
            )
        if self.inspect(observed.container_id) is not None:
            raise DockerContainerRuntimeError(
                "Docker container still exists after removal"
            )


__all__ = [
    "DockerCliManagedContainerProvider",
    "DockerContainerObservation",
    "DockerContainerRuntimeError",
    "DockerManagedContainerPort",
    "MANAGED_CONTAINER_LABEL",
    "MANAGED_CONTAINER_LABEL_VALUE",
]
