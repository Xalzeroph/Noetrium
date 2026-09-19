# vNext Boundary: artifact/content

SYSTEM = "artifact"
NODE = "artifact/content"
OWNS = "immutable content storage and content digest identity"
MUST_NOT_OWN = "business metadata"
AUTHORITY = "artifact_content"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
