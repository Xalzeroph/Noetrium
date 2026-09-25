from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.server.api import ServerOperationRecord
from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerTransportFailureKind

from ..api import (
    ServerDiagnosticIssue,
    ServerDiagnosticReport,
    ServerDiagnosticProjectorPort,
    ServerDiagnosticSeverity,
    ServerDiagnosticStatus,
    ServerHealthReport,
    ServerSessionDiagnostic,
)


class ServerDiagnosticProjector(ServerDiagnosticProjectorPort):
    """Project one server's already-observed control-plane facts.

    This module deliberately has no connection, journal writer, retry policy,
    or session controller. The composition root supplies observations from
    those adapters and this deep interface turns them into one stable report.
    """

    @staticmethod
    def _profile_mismatch(record: ServerOperationRecord, profile_digest: str) -> bool:
        return not record.started.profile_digest or record.started.profile_digest != profile_digest

    @staticmethod
    def _transport_issue(health: ServerHealthReport, server_id: str) -> ServerDiagnosticIssue:
        """Turn the transport result into a stable operator-facing cause.

        The raw transport result remains authoritative evidence. This mapping
        is only a diagnostic projection: it never changes readiness, retries a
        command or decides that an uncertain effect is safe.
        """

        mapping = {
            ServerTransportFailureKind.AUTHENTICATION: (
                "remote_authentication_failed",
                "SSH authentication failed before the health command completed",
                "verify_ssh_identity",
            ),
            ServerTransportFailureKind.NETWORK: (
                "remote_network_unreachable",
                "the controller could not establish the SSH network connection",
                "verify_server_route",
            ),
            ServerTransportFailureKind.TIMEOUT: (
                "remote_health_timeout",
                "the health probe exceeded the configured SSH command timeout",
                "inspect_network_or_remote_load",
            ),
            ServerTransportFailureKind.SPAWN_ERROR: (
                "controller_ssh_spawn_failed",
                "the controller could not start its configured SSH executable",
                "verify_controller_ssh_executable",
            ),
            ServerTransportFailureKind.REMOTE_EXIT: (
                "remote_health_command_failed",
                "SSH connected but the remote health command exited unsuccessfully",
                "inspect_remote_health_stderr",
            ),
            ServerTransportFailureKind.NONE: (
                "remote_health_unclassified_failure",
                "the health probe did not reach the server without a transport class",
                "inspect_health_probe_evidence",
            ),
        }
        code, summary, action = mapping[health.raw.failure_kind]
        return ServerDiagnosticIssue(
            code,
            ServerDiagnosticSeverity.ERROR,
            summary,
            evidence_refs=(
                f"server:{server_id}",
                f"transport:{health.raw.failure_kind.value}",
            ),
            recommended_action=action,
        )

    def project(
        self,
        *,
        server_id: str,
        profile_digest: str,
        operation_log: str,
        health: ServerHealthReport,
        pending_operations: tuple[ServerOperationRecord, ...],
        recent_operations: tuple[ServerOperationRecord, ...],
        session: ServerSessionDiagnostic | None = None,
    ) -> ServerDiagnosticReport:
        if health.server_id != server_id:
            raise ValueError("server diagnostic health identity differs from server identity")
        issues: list[ServerDiagnosticIssue] = []
        if not health.reachable:
            issues.append(self._transport_issue(health, server_id))
        if health.reachable and not health.platform_ready:
            issues.append(
                ServerDiagnosticIssue(
                    "platform_not_ready",
                    ServerDiagnosticSeverity.ERROR,
                    "remote host is reachable but one or more managed runtime identities are not ready",
                    evidence_refs=tuple(f"health-check:{name}" for name in health.issues),
                    recommended_action="inspect_health_checks",
                )
            )
        for issue in health.issues:
            issues.append(
                ServerDiagnosticIssue(
                    f"health:{issue}",
                    ServerDiagnosticSeverity.ERROR,
                    f"managed health check failed: {issue}",
                    evidence_refs=(f"health-check:{issue}",),
                    recommended_action="inspect_health_checks",
                )
            )

        if pending_operations:
            pending_refs = tuple(f"operation:{record.operation_id}" for record in pending_operations)
            mismatched = tuple(
                record
                for record in pending_operations
                if self._profile_mismatch(record, profile_digest)
            )
            if mismatched:
                issues.append(
                    ServerDiagnosticIssue(
                        "operation_profile_reconciliation_required",
                        ServerDiagnosticSeverity.ERROR,
                        "an uncertain operation belongs to an older or unidentified server profile; reconcile with that profile before mutation",
                        evidence_refs=tuple(f"operation:{record.operation_id}" for record in mismatched),
                        recommended_action="reconcile_with_original_profile",
                    )
                )
            else:
                issues.append(
                    ServerDiagnosticIssue(
                        "operation_reconciliation_required",
                        ServerDiagnosticSeverity.ERROR,
                        "an operation effect is uncertain; inspect and resolve it before another mutation",
                        evidence_refs=pending_refs,
                        recommended_action="reconcile_uncertain_operation",
                    )
                )

        historical_mismatch = tuple(
            record
            for record in recent_operations
            if self._profile_mismatch(record, profile_digest)
        )
        if historical_mismatch and not pending_operations:
            issues.append(
                ServerDiagnosticIssue(
                    "operation_history_profile_mismatch",
                    ServerDiagnosticSeverity.WARNING,
                    "recent operation history contains records from another or unidentified profile",
                    evidence_refs=tuple(f"operation:{record.operation_id}" for record in historical_mismatch),
                    recommended_action="inspect_profile_generation",
                )
            )

        if session is not None and session.state != "exact":
            issues.append(
                ServerDiagnosticIssue(
                    f"session:{session.state}",
                    ServerDiagnosticSeverity.WARNING,
                    f"persistent operator session is {session.state}: {session.summary}",
                    evidence_refs=tuple(session.evidence_refs),
                    recommended_action="inspect_session_binding",
                )
            )

        if pending_operations:
            status = ServerDiagnosticStatus.RECONCILIATION_REQUIRED
        elif not health.reachable or not health.platform_ready:
            status = ServerDiagnosticStatus.REMOTE_NOT_READY
        else:
            status = ServerDiagnosticStatus.READY
        return ServerDiagnosticReport(
            server_id=server_id,
            profile_digest=profile_digest,
            operation_log=operation_log,
            health=health,
            pending_operations=pending_operations,
            recent_operations=recent_operations,
            session=session,
            issues=tuple(issues),
            status=status,
        )


__all__ = ["ServerDiagnosticProjector"]
