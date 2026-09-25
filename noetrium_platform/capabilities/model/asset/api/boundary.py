# vNext Boundary: model/asset

SYSTEM = "model"
NODE = "model/asset"
OWNS = "immutable model asset identity and provenance"
MUST_NOT_OWN = "artifact byte storage"
AUTHORITY = "model_asset"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
