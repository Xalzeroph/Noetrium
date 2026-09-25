class StateVersionConflict(RuntimeError):
    pass


class StateCorruptionError(RuntimeError):
    pass


class StateBootstrapConflict(RuntimeError):
    """Persisted canonical state conflicts with a caller-supplied bootstrap value."""


__all__ = ["StateBootstrapConflict", "StateCorruptionError", "StateVersionConflict"]
