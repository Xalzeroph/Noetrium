# vNext Boundary: reliability/diagnostics

SYSTEM = "reliability"
NODE = "reliability/diagnostics"
OWNS = "read-side cross-system correlation and root-cause views"
MUST_NOT_OWN = "durable authority mutation"
AUTHORITY = "diagnostic_queries"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
