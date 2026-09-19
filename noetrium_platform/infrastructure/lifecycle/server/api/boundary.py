# vNext Boundary: runtime/server

SYSTEM = "runtime"
NODE = "runtime/server"
OWNS = "server identity, lifecycle and health contract"
MUST_NOT_OWN = "model serving truth"
AUTHORITY = "server_state"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
