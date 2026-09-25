# vNext Boundary: resource/directory

SYSTEM = "resource"
NODE = "resource/directory"
OWNS = "managed filesystem/directory identity and lifecycle"
MUST_NOT_OWN = "artifact immutable content"
AUTHORITY = "directory_inventory"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
