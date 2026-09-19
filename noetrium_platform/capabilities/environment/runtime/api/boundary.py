# vNext Boundary: environment/runtime

SYSTEM = "environment"
NODE = "environment/runtime"
OWNS = "environment runtime adapter contracts"
MUST_NOT_OWN = "environment catalog authority"
AUTHORITY = "environment_runtime_contract"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
