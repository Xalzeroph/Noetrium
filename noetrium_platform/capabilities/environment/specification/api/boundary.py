# vNext Boundary: environment/specification

SYSTEM = "environment"
NODE = "environment/specification"
OWNS = "environment definition and immutable spec identity"
MUST_NOT_OWN = "live host process state"
AUTHORITY = "environment_spec"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
