# vNext Boundary: environment/instance

SYSTEM = "environment"
NODE = "environment/instance"
OWNS = "environment instance identity, readiness and lifecycle"
MUST_NOT_OWN = "host supervision implementation"
AUTHORITY = "environment_instance"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
