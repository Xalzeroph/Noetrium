# vNext Boundary: governance/architecture

SYSTEM = "governance"
NODE = "governance/architecture"
OWNS = "architecture rules, dependencies and invariants"
MUST_NOT_OWN = "business state"
AUTHORITY = "architecture_policy"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
