# vNext Boundary: observability/telemetry

SYSTEM = "observability"
NODE = "observability/telemetry"
OWNS = "metrics/events/counters and telemetry routing"
MUST_NOT_OWN = "durable domain state"
AUTHORITY = "telemetry_observation"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
