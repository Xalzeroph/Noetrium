# vNext Boundary: observability/diagnostic

SYSTEM = "observability"
NODE = "observability/diagnostic"
OWNS = "operator-facing diagnostic correlation contracts"
MUST_NOT_OWN = "failure/state authority"
AUTHORITY = "diagnostic_view_contract"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
