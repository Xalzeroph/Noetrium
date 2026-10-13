# vNext Boundary: runtime/process

SYSTEM = "runtime"
NODE = "runtime/process"
OWNS = "process identity, launch contract and lifecycle"
MUST_NOT_OWN = "experiment semantics"
AUTHORITY = "process_state"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
