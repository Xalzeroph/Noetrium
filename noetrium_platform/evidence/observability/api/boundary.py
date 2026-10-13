# vNext Boundary: observability

SYSTEM = "observability"
NODE = "observability"
OWNS = "logs, telemetry, traces, status and observation projections"
MUST_NOT_OWN = "durable state/failure authority"
AUTHORITY = "observability"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
