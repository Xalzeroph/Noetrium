class ActionRecoveryRequired(RuntimeError):
    """An external action cannot continue without authoritative reconciliation."""


class ActionNotApplied(ActionRecoveryRequired):
    """Reconciliation proved that the intended external action was not applied."""


class ActionSafetyCapabilityMissing(RuntimeError):
    """Crash-safe action execution lacks a required recovery capability."""


class ActionScientificCommitContradiction(ActionRecoveryRequired):
    """Method commit proof contradicts authoritative action reconciliation."""


class EnvironmentCapabilityUnsupported(RuntimeError):
    """A provider explicitly does not implement an optional environment capability."""

    def __init__(self, capability: str) -> None:
        normalized = capability.strip()
        if not normalized:
            raise ValueError("environment capability must be non-empty")
        self.capability = normalized
        super().__init__(f"environment capability is unsupported: {normalized}")


__all__ = [
    "ActionNotApplied",
    "ActionRecoveryRequired",
    "ActionSafetyCapabilityMissing",
    "ActionScientificCommitContradiction",
    "EnvironmentCapabilityUnsupported",
]
