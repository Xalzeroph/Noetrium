# vNext Boundary: operator/maintenance

SYSTEM = "operator"
NODE = "operator/maintenance"
OWNS = "maintenance workflows and administrative actions"
MUST_NOT_OWN = "provider internals"
AUTHORITY = "operator_maintenance"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
