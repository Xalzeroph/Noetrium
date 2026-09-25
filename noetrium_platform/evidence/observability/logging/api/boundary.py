# vNext Boundary: observability/logging

SYSTEM = "observability"
NODE = "observability/logging"
OWNS = "structured logs, context, sinks, stores, queries, retention and capture"
MUST_NOT_OWN = "failure taxonomy and recovery"
AUTHORITY = "log_observation"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
