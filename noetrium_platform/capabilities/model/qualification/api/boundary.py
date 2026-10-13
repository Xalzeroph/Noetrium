# vNext Boundary: model/qualification

SYSTEM = "model"
NODE = "model/qualification"
OWNS = "model/runtime/host qualification evidence and compatibility claims"
MUST_NOT_OWN = "live capacity snapshots"
AUTHORITY = "model_qualification"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
