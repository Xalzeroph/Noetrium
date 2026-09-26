from __future__ import annotations

import json
from pathlib import Path
from time import monotonic

from noetrium_platform.foundation.kernel.kernel.retry import blocking_wait
from noetrium_platform.infrastructure.resources.container.api import (
    DockerCommandRunnerPort,
    DockerContainerObservation,
    DockerManagedContainerPort,
    LABEL_AUTHORITY,
    MANAGED_CONTAINER_LABEL,
    MANAGED_CONTAINER_LABEL_VALUE,
)


def discover_docker_root(
    runner: DockerCommandRunnerPort,
    *,
    docker_executable: str = "docker",
    command_timeout_seconds: float = 15.0,
) -> Path | None:
    """Best-effort discovery of the physical filesystem backing Docker state."""

    if not docker_executable.strip():
        raise ValueError("Docker executable is required")
    if command_timeout_seconds <= 0:
        raise ValueError("Docker command timeout must be positive")
    result = runner.run(
        (
            docker_executable,
            "info",
            "--format",
            "{{.DockerRootDir}}",
        ),
        timeout_seconds=float(command_timeout_seconds),
    )
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        return None
    return path.absolute()


class DockerContainerRuntimeError(RuntimeError):
    pass


class DockerCliManagedContainerProvider(DockerManagedContainerPort):
    """Observe/remove only explicitly Noetrium-labelled Docker containers."""

    def __init__(
        self,
        control_runner: DockerCommandRunnerPort,
        expansion_runner: DockerCommandRunnerPort,
        *,
        authority_id: str,
        docker_executable: str = "docker",
        command_timeout_seconds: float = 15.0,
    ) -> None:
        if (
            type(authority_id) is not str
            or len(authority_id) != 64
            or any(ch not in "0123456789abcdef" for ch in authority_id)
        ):
            raise ValueError("Docker authority_id must be lowercase sha256")
        if not docker_executable.strip():
            raise ValueError("docker executable is required")
        if command_timeout_seconds <= 0:
            raise ValueError("Docker command timeout must be positive")
        self._control_runner = control_runner
        self._expansion_runner = expansion_runner
        self._authority_id = authority_id
        self._docker = docker_executable
        self._timeout = float(command_timeout_seconds)

    @property
    def docker_executable(self) -> str:
        return self._docker

    def assert_expansion_admissible(self) -> None:
        """Fence storage-expanding Docker effects through the physical admission group."""

        result = self._expansion_runner.run(
            (
                self._docker,
                "info",
                "--format",
                "{{.DockerRootDir}}",
            ),
            timeout_seconds=self._timeout,
        )
        if result.returncode != 0:
            raise DockerContainerRuntimeError(
                "Docker expansion admission probe failed with exit code "
                f"{result.returncode}"
            )

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
            raise DockerContainerRuntimeError(
                "Docker inspect labels are not an object"
            )
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
        result = self._control_runner.run(
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
        result = self._control_runner.run(
            (
                self._docker,
                "ps",
                "-aq",
                "--filter",
                f"label={MANAGED_CONTAINER_LABEL}={MANAGED_CONTAINER_LABEL_VALUE}",
                "--filter",
                f"label={LABEL_AUTHORITY}={self._authority_id}",
            ),
            timeout_seconds=self._timeout,
        )
        if result.returncode != 0:
            raise DockerContainerRuntimeError(
                "Docker managed-container listing failed with exit code "
                f"{result.returncode}"
            )
        rows: list[DockerContainerObservation] = []
        for container_id in (
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip()
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
            blocking_wait(0.05)
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
        result = self._control_runner.run(tuple(argv), timeout_seconds=self._timeout)
        if result.returncode != 0 and not self._missing(result.stderr):
            # Docker can commit removal and then lose the command response when
            # the daemon/socket restarts. Re-observe the immutable container ID
            # before deciding. Absence is success; an unavailable daemon or a
            # still-present container remains fail-closed.
            try:
                remaining = self.inspect(observed.container_id)
            except Exception as exc:
                raise DockerContainerRuntimeError(
                    "Docker container removal outcome is unobservable"
                ) from exc
            if remaining is None:
                return
            raise DockerContainerRuntimeError(
                f"Docker container removal failed with exit code {result.returncode}"
            )
        if self.inspect(observed.container_id) is not None:
            raise DockerContainerRuntimeError(
                "Docker container still exists after removal"
            )


__all__ = [
    "DockerCliManagedContainerProvider",
    "DockerContainerRuntimeError",
    "discover_docker_root",
]
