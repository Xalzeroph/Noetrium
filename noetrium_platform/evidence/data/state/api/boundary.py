# vNext Boundary: data/state

SYSTEM = "data"
NODE = "data/state"
OWNS = "canonical mutable state and state-store contracts"
MUST_NOT_OWN = "disposable projections"
AUTHORITY = "state_authority"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
