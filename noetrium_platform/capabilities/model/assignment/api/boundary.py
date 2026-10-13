# vNext Boundary: model/assignment

SYSTEM = "model"
NODE = "model/assignment"
OWNS = "assign models to scope/run/participant roles"
MUST_NOT_OWN = "serving process lifecycle"
AUTHORITY = "model_assignment"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
