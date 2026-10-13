from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from time import monotonic

from noetrium_platform.foundation.kernel.kernel import JsonValue, blocking_wait
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.resources.authority.api import (
    is_physical_identity,
    is_realization_ticket,
    observation_field,
    physical_field,
    physical_identity,
    resource_observation,
    ticket_field,
)
from noetrium_platform.infrastructure.resources.container.api import (
    DockerCommandRunnerPort,
    EFFECT_LABEL,
    GENERATION_LABEL,
    MANAGED_CONTAINER_LABEL,
    MANAGED_CONTAINER_LABEL_VALUE,
    RESOURCE_LABEL,
    SPEC_LABEL,
    TICKET_LABEL,
)


def discover_docker_root(
    runner: DockerCommandRunnerPort,
    *,
    docker_executable: str = "docker",
    command_timeout_seconds: float = 15.0,
) -> Path | None:
    """Observe the Docker storage root without owning any lifecycle policy."""
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



class DockerPhysicalProviderError(RuntimeError):
    pass


class DockerPhysicalProvider:
    """Ticket-addressable Docker physical ISA.

    Policy is intentionally absent. Authority decides admission, generation,
    reuse and retirement. This provider only realizes, observes and retires one
    ticket-labelled Docker object.
    """

    provider_kind = "docker"

    def __init__(
        self,
        runner: DockerCommandRunnerPort,
        *,
        docker_executable: str = "docker",
        command_timeout_seconds: float = 60.0,
    ) -> None:
        if not docker_executable.strip():
            raise ValueError("docker executable is required")
        if command_timeout_seconds <= 0:
            raise ValueError("Docker command timeout must be positive")
        self._runner = runner
        self._docker = docker_executable
        self._timeout = float(command_timeout_seconds)

    @property
    def docker_executable(self) -> str:
        return self._docker

    @staticmethod
    def _missing(stderr: str) -> bool:
        lowered = stderr.casefold()
        return (
            "no such object" in lowered
            or "no such container" in lowered
        )

    @staticmethod
    def _labels(ticket: NoetriumUnit) -> tuple[tuple[str, str], ...]:
        return (
            (MANAGED_CONTAINER_LABEL, MANAGED_CONTAINER_LABEL_VALUE),
            (TICKET_LABEL, ticket_field(ticket, "ticket_id")),
            (EFFECT_LABEL, ticket_field(ticket, "effect_id")),
            (RESOURCE_LABEL, ticket_field(ticket, "resource_key")),
            (GENERATION_LABEL, str(ticket_field(ticket, "generation"))),
            (SPEC_LABEL, ticket_field(ticket, "spec_digest")),
        )

    @staticmethod
    def _container_name(ticket: NoetriumUnit) -> str:
        return "noetrium-" + ticket_field(ticket, "ticket_id")[:40]

    @staticmethod
    def _name_conflict(stderr: str) -> bool:
        lowered = stderr.casefold()
        return (
            "conflict" in lowered
            and "container name" in lowered
            and "already in use" in lowered
        )

    def _converge_name_race(
        self,
        ticket: NoetriumUnit,
        *,
        deadline: float,
    ) -> NoetriumUnit | None:
        """Adopt only the exact Authority identity that won a Docker name race.

        Docker name allocation is process-global while ResourceAuthority
        single-flight publication can be observed by multiple workers.  The
        loser must never retry creation or adopt a merely same-named foreign
        container.  Inspecting the deterministic name provides the earliest
        physical witness; Authority labels fence ticket/spec/generation.
        """
        name = self._container_name(ticket)
        while monotonic() < deadline:
            row = self._inspect(name)
            if row is not None:
                observation = self._observation_from_row(
                    row,
                    expected_ticket=ticket,
                )
                if observation_field(observation, "ready"):
                    identity = observation_field(
                        observation, "physical_identity"
                    )
                    assert identity is not None
                    return identity
            blocking_wait(0.05)
        return None

    def _inspect(self, reference: str) -> dict[str, object] | None:
        if not reference.strip():
            raise ValueError("Docker reference is required")
        result = self._runner.run(
            (self._docker, "inspect", reference),
            timeout_seconds=self._timeout,
        )
        if result.returncode != 0:
            if self._missing(result.stderr):
                return None
            raise DockerPhysicalProviderError(
                f"Docker inspect failed with exit code {result.returncode}"
            )
        try:
            payload = json.loads(result.stdout)
            if not isinstance(payload, list) or len(payload) != 1:
                raise TypeError("inspect cardinality")
            row = payload[0]
            if not isinstance(row, dict):
                raise TypeError("inspect row")
            config = row["Config"]
            state = row["State"]
            if not isinstance(config, dict) or not isinstance(state, dict):
                raise TypeError("inspect sections")
            labels = config.get("Labels") or {}
            if not isinstance(labels, dict):
                raise TypeError("inspect labels")
            return {
                "container_id": str(row["Id"]),
                "name": str(row["Name"]).lstrip("/"),
                "image": str(config["Image"]),
                "running": bool(state["Running"]),
                "pid": int(state.get("Pid") or 0),
                "started_at": str(state.get("StartedAt") or ""),
                "labels": {
                    str(key): str(value)
                    for key, value in labels.items()
                },
            }
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise DockerPhysicalProviderError(
                "Docker inspect returned malformed state"
            ) from exc

    def _find_ticket(self, ticket: NoetriumUnit) -> dict[str, object] | None:
        result = self._runner.run(
            (
                self._docker,
                "ps",
                "-aq",
                "--no-trunc",
                "--filter",
                f"label={MANAGED_CONTAINER_LABEL}={MANAGED_CONTAINER_LABEL_VALUE}",
                "--filter",
                f"label={TICKET_LABEL}={ticket_field(ticket, "ticket_id")}",
            ),
            timeout_seconds=self._timeout,
        )
        if result.returncode != 0:
            raise DockerPhysicalProviderError(
                "Docker ticket lookup failed with exit code "
                f"{result.returncode}"
            )
        refs = tuple(
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip()
        )
        if len(refs) > 1:
            raise DockerPhysicalProviderError(
                "one Authority ticket resolved to multiple Docker containers"
            )
        if not refs:
            return None
        row = self._inspect(refs[0])
        if row is None:
            return None
        labels = row["labels"]
        assert isinstance(labels, dict)
        expected = dict(self._labels(ticket))
        for key, value in expected.items():
            if labels.get(key) != value:
                raise DockerPhysicalProviderError(
                    "Docker ticket labels drifted from Authority identity"
                )
        return row

    @staticmethod
    def _ticket_from_labels(
        labels: Mapping[str, str],
    ) -> tuple[str, str, int, str]:
        try:
            resource_key = labels[RESOURCE_LABEL]
            ticket_id = labels[TICKET_LABEL]
            generation = int(labels[GENERATION_LABEL])
            spec_digest = labels[SPEC_LABEL]
        except (KeyError, TypeError, ValueError) as exc:
            raise DockerPhysicalProviderError(
                "Docker physical identity lacks Authority labels"
            ) from exc
        if (
            not resource_key
            or not ticket_id
            or generation < 1
            or not spec_digest
        ):
            raise DockerPhysicalProviderError(
                "Docker Authority labels are invalid"
            )
        return resource_key, ticket_id, generation, spec_digest

    def _observation_from_row(
        self,
        row: dict[str, object],
        *,
        expected_ticket: NoetriumUnit | None = None,
    ) -> NoetriumUnit:
        labels = row["labels"]
        if not isinstance(labels, dict):
            raise DockerPhysicalProviderError("Docker labels are invalid")
        resource_key, ticket_id, generation, spec_digest = (
            self._ticket_from_labels(labels)
        )
        if expected_ticket is not None and (
            resource_key != ticket_field(expected_ticket, "resource_key")
            or ticket_id != ticket_field(expected_ticket, "ticket_id")
            or generation != ticket_field(expected_ticket, "generation")
            or spec_digest != ticket_field(expected_ticket, "spec_digest")
        ):
            raise DockerPhysicalProviderError(
                "Docker observation crossed Authority ticket identity"
            )
        identity = physical_identity(
            self.provider_kind,
            str(row["container_id"]),
            {
                "name": str(row["name"]),
                "image": str(row["image"]),
                "pid": int(row["pid"]),
                "started_at": str(row["started_at"]),
                "ticket_id": ticket_id,
                "resource_key": resource_key,
                "generation": generation,
                "spec_digest": spec_digest,
            },
        )
        running = bool(row["running"])
        return resource_observation(
            resource_key=resource_key,
            generation=generation,
            ticket_id=ticket_id,
            spec_digest=spec_digest,
            exists=True,
            ready=running,
            physical=identity,
            evidence={
                "container_id": str(row["container_id"]),
                "running": running,
            },
        )

    def observe(
        self,
        reference: NoetriumUnit,
    ) -> NoetriumUnit:
        if is_realization_ticket(reference):
            row = self._find_ticket(reference)
            if row is None:
                return resource_observation(
                    ticket_field(reference, "resource_key"),
                    ticket_field(reference, "generation"),
                    ticket_field(reference, "ticket_id"),
                    ticket_field(reference, "spec_digest"),
                    False,
                    False,
                    None,
                )
            return self._observation_from_row(
                row,
                expected_ticket=reference,
            )
        if not is_physical_identity(reference):
            raise TypeError(
                "Docker observe requires ticket or physical-identity Unit"
            )
        if physical_field(reference, "provider_kind") != self.provider_kind:
            raise ValueError("foreign physical identity passed to Docker provider")
        row = self._inspect(physical_field(reference, "physical_id"))
        attributes = dict(physical_field(reference, "attributes") or {})
        resource_key = str(attributes.get("resource_key") or "")
        ticket_id = str(attributes.get("ticket_id") or "")
        spec_digest = str(attributes.get("spec_digest") or "")
        generation_value = attributes.get("generation")
        if (
            not resource_key
            or not ticket_id
            or not spec_digest
            or type(generation_value) is not int
            or generation_value < 1
        ):
            raise DockerPhysicalProviderError(
                "physical identity lacks Authority ticket metadata"
            )
        if row is None:
            return resource_observation(
                resource_key,
                generation_value,
                ticket_id,
                spec_digest,
                False,
                False,
                None,
            )
        return self._observation_from_row(row)

    @staticmethod
    def _run_args(spec: Mapping[str, JsonValue]) -> tuple[str, ...]:
        raw = spec.get("run_args")
        if not isinstance(raw, (tuple, list)) or not raw:
            raise ValueError(
                "Docker realization spec requires non-empty run_args"
            )
        args = tuple(str(value) for value in raw)
        if any(not value for value in args):
            raise ValueError("Docker run arguments must be non-empty")
        forbidden = {"--name", "--label", "-l"}
        if any(value in forbidden for value in args):
            raise ValueError(
                "Docker run_args cannot override Authority identity labels/name"
            )
        if "-d" not in args and "--detach" not in args:
            raise ValueError(
                "Authority-managed Docker realizations must run detached"
            )
        return args

    def realize(
        self,
        spec: Mapping[str, JsonValue],
        ticket: NoetriumUnit,
    ) -> NoetriumUnit:
        existing = self.observe(ticket)
        if observation_field(existing, "exists"):
            if observation_field(existing, "ready"):
                assert observation_field(existing, "physical_identity") is not None
                return observation_field(existing, "physical_identity")
            identity = observation_field(existing, "physical_identity")
            assert identity is not None
            result = self._runner.run(
                (self._docker, "start", physical_field(identity, "physical_id")),
                timeout_seconds=self._timeout,
            )
            if result.returncode != 0:
                raise DockerPhysicalProviderError(
                    "Docker exact-ticket start failed with exit code "
                    f"{result.returncode}"
                )
        else:
            argv = [
                self._docker,
                "run",
                "--name",
                self._container_name(ticket),
            ]
            for key, value in self._labels(ticket):
                argv.extend(("--label", f"{key}={value}"))
            argv.extend(self._run_args(spec))
            result = self._runner.run(
                tuple(argv),
                timeout_seconds=self._timeout,
            )
            if result.returncode != 0:
                if not self._name_conflict(result.stderr):
                    raise DockerPhysicalProviderError(
                        "Docker realization failed with exit code "
                        f"{result.returncode}: {result.stderr.strip()}"
                    )
                # Same-ticket workers can race between Authority single-flight
                # publication and Docker's process-global name reservation.
                # Converge on the exact labelled winner; never retry creation.
                raced = self._converge_name_race(
                    ticket,
                    deadline=monotonic() + self._timeout,
                )
                if raced is not None:
                    return raced
                raise DockerPhysicalProviderError(
                    "Docker exact-ticket name race did not converge before "
                    "timeout; ticket=" + str(ticket_field(ticket, "ticket_id"))
                )

        deadline = monotonic() + self._timeout
        while monotonic() < deadline:
            observed = self.observe(ticket)
            if observation_field(observed, "exists") and observation_field(observed, "ready"):
                assert observation_field(observed, "physical_identity") is not None
                return observation_field(observed, "physical_identity")
            blocking_wait(0.05)
        raise DockerPhysicalProviderError(
            "Docker realization did not become ready before timeout"
        )

    def retire(
        self,
        reference: NoetriumUnit,
        ticket: NoetriumUnit,
    ) -> NoetriumUnit:
        observed = self.observe(ticket)
        if not observation_field(observed, "exists"):
            return observed
        identity = observation_field(observed, "physical_identity")
        assert identity is not None
        if is_physical_identity(reference):
            if (
                physical_field(reference, "provider_kind") != self.provider_kind
                or physical_field(reference, "physical_id") != physical_field(identity, "physical_id")
            ):
                raise DockerPhysicalProviderError(
                    "retire reference does not match Authority ticket"
                )
        result = self._runner.run(
            (self._docker, "rm", "-f", physical_field(identity, "physical_id")),
            timeout_seconds=self._timeout,
        )
        if result.returncode != 0 and not self._missing(result.stderr):
            remaining = self.observe(ticket)
            if observation_field(remaining, "exists"):
                raise DockerPhysicalProviderError(
                    "Docker retirement outcome remained present"
                )
        final = self.observe(ticket)
        if observation_field(final, "exists"):
            raise DockerPhysicalProviderError(
                "Docker container survived retirement"
            )
        return final


__all__ = [
    "DockerPhysicalProvider",
    "DockerPhysicalProviderError",
    "discover_docker_root",
]
