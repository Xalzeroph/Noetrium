# vNext Boundary: runtime/host

SYSTEM = "runtime"
NODE = "runtime/host"
OWNS = "live host identity and runtime host attachment"
MUST_NOT_OWN = "resource catalog metadata"
AUTHORITY = "host_runtime_state"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
