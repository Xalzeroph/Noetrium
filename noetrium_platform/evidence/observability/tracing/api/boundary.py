# vNext Boundary: observability/tracing

SYSTEM = "observability"
NODE = "observability/tracing"
OWNS = "trace/span identity and propagation"
MUST_NOT_OWN = "business operation truth"
AUTHORITY = "trace_observation"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
