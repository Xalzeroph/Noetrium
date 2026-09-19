# vNext Boundary: operator/query

SYSTEM = "operator"
NODE = "operator/query"
OWNS = "operator read/query contracts"
MUST_NOT_OWN = "durable state mutation"
AUTHORITY = "operator_queries"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
