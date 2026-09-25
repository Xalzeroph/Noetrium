from __future__ import annotations

from scripts.server_health import ready_for_mutation


def test_server_health_is_not_writable_when_reconciliation_is_pending() -> None:
    assert not ready_for_mutation(platform_ready=True, pending_operations=(object(),))


def test_server_health_is_writable_only_when_remote_platform_is_ready_and_reconciled() -> None:
    assert ready_for_mutation(platform_ready=True, pending_operations=())
    assert not ready_for_mutation(platform_ready=False, pending_operations=())
