# vNext Boundary: platform

SYSTEM = "platform"
NODE = "platform"
OWNS = "platform lifecycle, global identity, composition boundaries"
MUST_NOT_OWN = "domain business state and child internals"
AUTHORITY = "platform_identity"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
