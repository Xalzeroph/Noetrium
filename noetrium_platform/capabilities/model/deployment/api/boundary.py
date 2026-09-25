# vNext Boundary: model/deployment

SYSTEM = "model"
NODE = "model/deployment"
OWNS = "deployment identity, exact closure and lifecycle contract"
MUST_NOT_OWN = "server process implementation"
AUTHORITY = "model_deployment"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
