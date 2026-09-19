class TelemetryMetricCorruptionError(ValueError):
    """Persisted telemetry cannot be decoded without changing its meaning."""


__all__ = ["TelemetryMetricCorruptionError"]
