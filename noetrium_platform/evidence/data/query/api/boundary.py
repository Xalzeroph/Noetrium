# vNext Boundary: data/query

SYSTEM = "data"
NODE = "data/query"
OWNS = "read query contracts spanning non-authoritative projections"
MUST_NOT_OWN = "durable writes"
AUTHORITY = "query_contracts"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
