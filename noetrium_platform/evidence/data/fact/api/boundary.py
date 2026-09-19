# vNext Boundary: data/fact

SYSTEM = "data"
NODE = "data/fact"
OWNS = "durable fact envelopes and authoritative fact writes"
MUST_NOT_OWN = "business-specific state transitions"
AUTHORITY = "fact_authority"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
