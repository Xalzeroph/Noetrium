# vNext Boundary: artifact/catalog

SYSTEM = "artifact"
NODE = "artifact/catalog"
OWNS = "artifact metadata and logical identity catalog"
MUST_NOT_OWN = "content bytes mutation"
AUTHORITY = "artifact_catalog"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
