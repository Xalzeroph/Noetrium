from __future__ import annotations

from types import SimpleNamespace

import pytest

from noetrium_platform.infrastructure.resources.authority import (
    TicketState,
    physical_field,
    realization_ticket,
    resource_observation,
    ticket_field,
)
from noetrium_platform.infrastructure.resources.container.api import (
    EFFECT_LABEL,
    GENERATION_LABEL,
    MANAGED_CONTAINER_LABEL,
    MANAGED_CONTAINER_LABEL_VALUE,
    RESOURCE_LABEL,
    SPEC_LABEL,
    TICKET_LABEL,
)
from noetrium_platform.infrastructure.resources.container.providers.docker_physical import (
    DockerPhysicalProvider,
    DockerPhysicalProviderError,
)


def _ticket():
    return realization_ticket(
        "a" * 64,
        "effect",
        "realization",
        "container:test",
        "docker",
        1,
        "b" * 64,
        "holder",
        TicketState.BOUND,
    )


def _row(ticket, *, ticket_id: str | None = None, running: bool = True):
    tid = ticket_id or str(ticket_field(ticket, "ticket_id"))
    return {
        "container_id": "physical-winner",
        "name": "noetrium-" + str(ticket_field(ticket, "ticket_id"))[:40],
        "image": "sha256:test",
        "running": running,
        "pid": 1234 if running else 0,
        "started_at": "2026-10-11T00:00:00Z",
        "labels": {
            MANAGED_CONTAINER_LABEL: MANAGED_CONTAINER_LABEL_VALUE,
            TICKET_LABEL: tid,
            EFFECT_LABEL: str(ticket_field(ticket, "effect_id")),
            RESOURCE_LABEL: str(ticket_field(ticket, "resource_key")),
            GENERATION_LABEL: str(ticket_field(ticket, "generation")),
            SPEC_LABEL: str(ticket_field(ticket, "spec_digest")),
        },
    }


class _Runner:
    def __init__(self, stderr: str):
        self.stderr = stderr
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv, *, timeout_seconds):
        del timeout_seconds
        self.calls.append(tuple(argv))
        if len(argv) >= 2 and argv[1] == "run":
            return SimpleNamespace(returncode=125, stdout="", stderr=self.stderr)
        raise AssertionError(f"unexpected runner call: {argv}")


class _RaceProvider(DockerPhysicalProvider):
    def __init__(self, runner, rows):
        super().__init__(runner, command_timeout_seconds=0.20)
        self._rows = list(rows)
        self._observe_count = 0

    def observe(self, reference):
        self._observe_count += 1
        return resource_observation(
            str(ticket_field(reference, "resource_key")),
            int(ticket_field(reference, "generation")),
            str(ticket_field(reference, "ticket_id")),
            str(ticket_field(reference, "spec_digest")),
            False,
            False,
            None,
        )

    def _inspect(self, reference):
        del reference
        if not self._rows:
            return None
        value = self._rows.pop(0)
        return value


def test_name_conflict_converges_on_exact_ticket_winner_without_second_create():
    ticket = _ticket()
    runner = _Runner(
        'docker: Error response from daemon: Conflict. The container name '
        '"/noetrium-x" is already in use by container "winner".'
    )
    provider = _RaceProvider(runner, [None, _row(ticket)])

    identity = provider.realize({"run_args": ["-d", "image"]}, ticket)

    assert physical_field(identity, "physical_id") == "physical-winner"
    assert len([call for call in runner.calls if call[1] == "run"]) == 1


def test_name_conflict_never_adopts_same_name_with_foreign_ticket_identity():
    ticket = _ticket()
    runner = _Runner(
        'docker: Error response from daemon: Conflict. The container name '
        '"/noetrium-x" is already in use by container "foreign".'
    )
    provider = _RaceProvider(runner, [_row(ticket, ticket_id="c" * 64)])

    with pytest.raises(
        DockerPhysicalProviderError,
        match="crossed Authority ticket identity",
    ):
        provider.realize({"run_args": ["-d", "image"]}, ticket)
    assert len([call for call in runner.calls if call[1] == "run"]) == 1


def test_non_conflict_docker_failure_fails_immediately_without_race_adoption():
    ticket = _ticket()
    runner = _Runner("docker: daemon unavailable")
    provider = _RaceProvider(runner, [_row(ticket)])

    with pytest.raises(DockerPhysicalProviderError, match="daemon unavailable"):
        provider.realize({"run_args": ["-d", "image"]}, ticket)
    assert provider._rows == [_row(ticket)]
