# vNext Boundary: runtime/session

SYSTEM = "runtime"
NODE = "runtime/session"
OWNS = "runtime session identity and host/process bindings"
MUST_NOT_OWN = "participant scientific semantics"
AUTHORITY = "runtime_session"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
