from __future__ import annotations

from noetrium_platform.infrastructure.reliability.recovery.api import (
    RecoveryActionCode,
    RecoveryAutomation,
    RecoveryRecommendation,
)
from noetrium_platform.evidence.observability.status.api import SubsystemSnapshot

from .runtime_recovery_rules import DEFAULT_RECOVERY_RULES, RecoveryRule


def _recommendation(
    snapshot: SubsystemSnapshot,
    rule: RecoveryRule,
    reasons: tuple[str, ...],
) -> RecoveryRecommendation:
    return RecoveryRecommendation(
        snapshot.subsystem,
        rule.action,
        rule.automation,
        reasons,
        required_checks=rule.required_checks,
    )


def classify_snapshot_recovery(
    snapshot: SubsystemSnapshot,
    *,
    rules: tuple[RecoveryRule, ...] = DEFAULT_RECOVERY_RULES,
) -> tuple[RecoveryRecommendation, ...]:
    """Pure ordered rule evaluation over structured status reason codes."""

    if not snapshot.reason_codes:
        return ()
    consumed: set[str] = set()
    recommendations: list[RecoveryRecommendation] = []
    for rule in rules:
        matched = tuple(code for code in rule.match(snapshot.reason_codes) if code not in consumed)
        if not matched:
            continue
        consumed.update(matched)
        recommendations.append(_recommendation(snapshot, rule, matched))
        if rule.terminal:
            return tuple(recommendations)

    unknown = tuple(code for code in snapshot.reason_codes if code not in consumed)
    if unknown:
        recommendations.append(
            RecoveryRecommendation(
                snapshot.subsystem,
                RecoveryActionCode.MANUAL_DIAGNOSIS,
                RecoveryAutomation.FORBIDDEN,
                unknown,
                required_checks=("inspect_unclassified_status_reason",),
            )
        )
    return tuple(recommendations)


__all__ = ["classify_snapshot_recovery"]
