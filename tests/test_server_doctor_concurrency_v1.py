from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from scripts import server_doctor


def test_doctor_inspect_binds_server_composition_to_cli_task_group(monkeypatch) -> None:
    entry = SimpleNamespace(composition_ready=True, missing_profile_fields=())
    catalog = SimpleNamespace(
        entry=lambda server_id: entry,
        environment_for=lambda server_id: {"selected": server_id},
    )
    monkeypatch.setattr(server_doctor, "compose_script_server_catalog", lambda profile: ({}, catalog))

    task_group = object()

    @contextmanager
    def scope(scope_id):
        assert scope_id == "server-doctor"
        yield task_group

    captured = {}

    def compose(server_id, *, environ, task_group):
        captured.update(server_id=server_id, environ=environ, task_group=task_group)
        raise RuntimeError("stop-after-compose")

    monkeypatch.setattr(server_doctor, "server_cli_concurrency_scope", scope)
    monkeypatch.setattr(server_doctor, "compose_server_from_environment", compose)

    args = SimpleNamespace(profile_file="fleet.env", server_id="server-a", session=None, recent_limit=5)
    with pytest.raises(RuntimeError, match="stop-after-compose"):
        server_doctor._inspect(args)

    assert captured == {"server_id": "server-a", "environ": {"selected": "server-a"}, "task_group": task_group}
