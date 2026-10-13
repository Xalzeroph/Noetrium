from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.infrastructure.reliability.recovery.api import RecoveryActionCode, RecoveryAutomation


@dataclass(frozen=True, slots=True)
class RecoveryRule:
    """Declarative mapping from status reason codes to one recovery recommendation."""

    action: RecoveryActionCode
    automation: RecoveryAutomation
    required_checks: tuple[str, ...] = ()
    exact_codes: frozenset[str] = frozenset()
    prefixes: tuple[str, ...] = ()
    terminal: bool = False

    def match(self, reason_codes: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            code
            for code in reason_codes
            if code in self.exact_codes or any(code.startswith(prefix) for prefix in self.prefixes)
        )


IDENTITY_DRIFT_RULE = RecoveryRule(
    RecoveryActionCode.BLOCK_IDENTITY_DRIFT,
    RecoveryAutomation.FORBIDDEN,
    ("verify_frozen_identity", "inspect_authoritative_binding"),
    exact_codes=frozenset(
        {
            "binding_drift",
            "transport_identity_drift",
            "session_identity_drift",
            "controller_command_drift",
            "controller_cwd_drift",
            "stack_digest_drift",
            "qualification_digest_drift",
        }
    ),
    terminal=True,
)

DEFAULT_RECOVERY_RULES: tuple[RecoveryRule, ...] = (
    IDENTITY_DRIFT_RULE,
    RecoveryRule(
        RecoveryActionCode.VERIFY_EVIDENCE,
        RecoveryAutomation.FORBIDDEN,
        ("verify_runtime_history_hash_chain", "verify_authoritative_runtime_state"),
        exact_codes=frozenset({"runtime_history_integrity"}),
    ),
    RecoveryRule(
        RecoveryActionCode.RECONCILE_RUNTIME_HISTORY,
        RecoveryAutomation.CONDITIONAL,
        ("verify_runtime_history_hash_chain", "verify_authoritative_runtime_state"),
        exact_codes=frozenset({"runtime_history_tail_mismatch"}),
    ),
    RecoveryRule(
        RecoveryActionCode.RECONCILE_RUNTIME_TRANSACTION,
        RecoveryAutomation.CONDITIONAL,
        ("acquire_recovery_execution_fence", "reconcile_current_runtime_action"),
        exact_codes=frozenset({"runtime_transaction_in_progress"}),
    ),
    RecoveryRule(
        RecoveryActionCode.RECONCILE_RUNTIME_TRANSACTION,
        RecoveryAutomation.CONDITIONAL,
        ("acquire_recovery_execution_fence", "reconcile_current_runtime_action"),
        exact_codes=frozenset({"runtime_recovery_required"}),
    ),
    RecoveryRule(
        RecoveryActionCode.MANUAL_DIAGNOSIS,
        RecoveryAutomation.FORBIDDEN,
        ("locate_runtime_failure", "verify_effect_certainty"),
        exact_codes=frozenset({"runtime_transaction_failed"}),
    ),
    RecoveryRule(
        RecoveryActionCode.RECONCILE_RECOVERY_OWNERSHIP,
        RecoveryAutomation.CONDITIONAL,
        ("verify_prior_owner_not_running",),
        exact_codes=frozenset({"recovery_lease_expired"}),
    ),
    RecoveryRule(
        RecoveryActionCode.RECONCILE_PERSISTENT_SESSION,
        RecoveryAutomation.CONDITIONAL,
        ("verify_runtime_state", "verify_service_state", "verify_frozen_session_binding"),
        exact_codes=frozenset({"session_missing", "binding_missing"}),
    ),
    RecoveryRule(
        RecoveryActionCode.RECONCILE_SESSION_CONTROL,
        RecoveryAutomation.CONDITIONAL,
        ("verify_session_backend_control", "verify_runtime_state", "verify_service_state"),
        exact_codes=frozenset(
            {"control_unavailable", "verification_unavailable", "controller_not_live"}
        ),
    ),
    RecoveryRule(
        RecoveryActionCode.MANUAL_DIAGNOSIS,
        RecoveryAutomation.FORBIDDEN,
        ("verify_service_start_intent_integrity",),
        exact_codes=frozenset({"multiple_unresolved_start_intents"}),
    ),
    RecoveryRule(
        RecoveryActionCode.RECONCILE_SERVICE_START,
        RecoveryAutomation.CONDITIONAL,
        ("reconcile_prepared_service_start",),
        exact_codes=frozenset({"unresolved_start_intent"}),
    ),
    RecoveryRule(
        RecoveryActionCode.RECONCILE_SERVICE,
        RecoveryAutomation.CONDITIONAL,
        ("verify_exact_service_contract", "reconcile_service_process"),
        exact_codes=frozenset({"service_recovery_required"}),
        prefixes=("service_phase_",),
    ),
    RecoveryRule(
        RecoveryActionCode.RECONCILE_MODEL_SERVICE,
        RecoveryAutomation.CONDITIONAL,
        ("verify_exact_service_state", "verify_process_identity", "verify_runtime_qualification"),
        exact_codes=frozenset({"heartbeat_missing", "stale_heartbeat", "not_ready"}),
    ),
    RecoveryRule(
        RecoveryActionCode.REBUILD_DERIVED_STATE,
        RecoveryAutomation.SAFE,
        exact_codes=frozenset({"forensic_projection_stale"}),
    ),
    RecoveryRule(
        RecoveryActionCode.VERIFY_EVIDENCE,
        RecoveryAutomation.CONDITIONAL,
        ("classify_unclosed_invocations_as_active_or_interrupted",),
        exact_codes=frozenset({"unclosed_operation_invocations"}),
    ),
)


__all__ = ["DEFAULT_RECOVERY_RULES", "IDENTITY_DRIFT_RULE", "RecoveryRule"]
