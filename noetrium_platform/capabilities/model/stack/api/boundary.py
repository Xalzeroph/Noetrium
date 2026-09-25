# vNext Boundary: model/stack

SYSTEM = "model"
NODE = "model/stack"
OWNS = "model stack composition and runtime build identity"
MUST_NOT_OWN = "server health"
AUTHORITY = "model_stack"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
