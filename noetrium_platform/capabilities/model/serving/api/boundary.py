# vNext Boundary: model/serving

SYSTEM = "model"
NODE = "model/serving"
OWNS = "serving endpoint contract and request routing semantics"
MUST_NOT_OWN = "model catalog metadata"
AUTHORITY = "model_serving"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
