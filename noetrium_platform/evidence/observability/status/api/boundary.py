# vNext Boundary: observability/status

SYSTEM = "observability"
NODE = "observability/status"
OWNS = "health/status observations and status projections"
MUST_NOT_OWN = "authoritative lifecycle state"
AUTHORITY = "status_observation"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
