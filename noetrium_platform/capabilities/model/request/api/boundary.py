# vNext Boundary: model/request

SYSTEM = "model"
NODE = "model/request"
OWNS = "model request identity, exact input contract and response envelope"
MUST_NOT_OWN = "business result semantics"
AUTHORITY = "model_request"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
