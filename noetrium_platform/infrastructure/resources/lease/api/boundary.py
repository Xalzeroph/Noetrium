# vNext Boundary: resource/lease

SYSTEM = "resource"
NODE = "resource/lease"
OWNS = "lease identity, acquisition, renewal and release"
MUST_NOT_OWN = "server lifecycle"
AUTHORITY = "resource_lease"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
