# vNext Boundary: model/catalog

SYSTEM = "model"
NODE = "model/catalog"
OWNS = "model families/revisions catalog and metadata"
MUST_NOT_OWN = "live deployment state"
AUTHORITY = "model_catalog"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
