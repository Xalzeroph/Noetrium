class TaskCompletionSafetyCapabilityMissing(RuntimeError):
    """Crash-durable external effects require a stable, idempotent method completion key."""
