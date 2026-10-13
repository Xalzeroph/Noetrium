from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.server.api import (
    ServerOperationEffect,
    ServerOperationKind,
    ServerOperationStarted,
)
import pytest

from noetrium_platform.infrastructure.lifecycle.server.health.api import (
    ServerDiagnosticStatus,
    ServerHealthReport,
    ServerSessionDiagnostic,
)
from noetrium_platform.infrastructure.lifecycle.server.health.runtime import ServerDiagnosticProjector
from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerCommandResult
from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerTransportFailureKind


def _health(
    *,
    server_id: str = "server-a",
    ready: bool = True,
    failure_kind: ServerTransportFailureKind = ServerTransportFailureKind.NONE,
) -> ServerHealthReport:
    return ServerHealthReport(
        server_id=server_id,
        reachable=ready,
        host_name="remote",
        python_version="3.10",
        git_version=None,
        tmux_version=None,
        raw=ServerCommandResult(
            server_id,
            "health",
            0 if ready else 255,
            "",
            "",
            failure_kind=failure_kind,
        ),
        platform_ready=ready,
        checks=() if ready else (("python_binary_identity", "mismatch"),),
        issues=() if ready else ("python_binary_identity",),
    )


def _pending(*, profile_digest: str) -> object:
    return ServerOperationStarted(
        "op-uncertain",
        "server-a",
        ServerOperationKind.FILE_UPLOAD,
        "request-digest",
        1.0,
        False,
        profile_digest,
        ServerOperationEffect.MUTATION,
    )


def test_diagnostic_marks_old_profile_uncertainty_as_actionable() -> None:
    from noetrium_platform.infrastructure.lifecycle.server.api import ServerOperationRecord

    record = ServerOperationRecord(_pending(profile_digest="old-profile"))
    report = ServerDiagnosticProjector().project(
        server_id="server-a",
        profile_digest="current-profile",
        operation_log="/tmp/server-operations.jsonl",
        health=_health(),
        pending_operations=(record,),
        recent_operations=(record,),
    )

    assert report.status == ServerDiagnosticStatus.RECONCILIATION_REQUIRED
    assert not report.ready_for_mutation
    assert report.issues[0].code == "operation_profile_reconciliation_required"


def test_diagnostic_joins_exact_health_and_session_without_command_side_effects() -> None:
    session = ServerSessionDiagnostic(
        "noetrium-shell",
        "drift",
        "controller command differs",
        reason_code="controller_command_drift",
        evidence_refs=("session-binding:abc",),
    )
    report = ServerDiagnosticProjector().project(
        server_id="server-a",
        profile_digest="current-profile",
        operation_log="/tmp/server-operations.jsonl",
        health=_health(),
        pending_operations=(),
        recent_operations=(),
        session=session,
    )

    assert report.status == ServerDiagnosticStatus.READY
    assert report.ready_for_mutation
    assert report.session == session
    assert report.issues[0].code == "session:drift"


@pytest.mark.parametrize(
    ("failure_kind", "code", "action"),
    (
        (
            ServerTransportFailureKind.AUTHENTICATION,
            "remote_authentication_failed",
            "verify_ssh_identity",
        ),
        (ServerTransportFailureKind.NETWORK, "remote_network_unreachable", "verify_server_route"),
        (ServerTransportFailureKind.TIMEOUT, "remote_health_timeout", "inspect_network_or_remote_load"),
        (
            ServerTransportFailureKind.SPAWN_ERROR,
            "controller_ssh_spawn_failed",
            "verify_controller_ssh_executable",
        ),
        (
            ServerTransportFailureKind.REMOTE_EXIT,
            "remote_health_command_failed",
            "inspect_remote_health_stderr",
        ),
    ),
)
def test_diagnostic_preserves_transport_root_cause_and_next_action(
    failure_kind: ServerTransportFailureKind,
    code: str,
    action: str,
) -> None:
    report = ServerDiagnosticProjector().project(
        server_id="server-a",
        profile_digest="current-profile",
        operation_log="/tmp/server-operations.jsonl",
        health=_health(ready=False, failure_kind=failure_kind),
        pending_operations=(),
        recent_operations=(),
    )

    issue = report.issues[0]
    assert issue.code == code
    assert issue.recommended_action == action
    assert f"transport:{failure_kind.value}" in issue.evidence_refs
