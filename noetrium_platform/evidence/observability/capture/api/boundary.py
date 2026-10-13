# vNext Boundary: observability/capture

SYSTEM = "observability"
NODE = "observability/capture"
OWNS = "raw byte/event/process capture contracts"
MUST_NOT_OWN = "semantic log interpretation"
AUTHORITY = "capture_observation"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
