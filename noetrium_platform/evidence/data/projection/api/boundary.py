# vNext Boundary: data/projection

SYSTEM = "data"
NODE = "data/projection"
OWNS = "derived read models and projection lifecycle"
MUST_NOT_OWN = "source-of-truth mutation"
AUTHORITY = "projection_authority"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
