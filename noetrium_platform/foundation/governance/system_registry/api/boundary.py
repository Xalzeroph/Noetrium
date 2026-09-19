# vNext Boundary: governance/system_registry

SYSTEM = "governance"
NODE = "governance/system_registry"
OWNS = "recursive system topology and ownership declarations"
MUST_NOT_OWN = "runtime orchestration"
AUTHORITY = "system_topology"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
