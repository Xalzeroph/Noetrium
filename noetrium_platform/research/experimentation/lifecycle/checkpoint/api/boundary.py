# vNext Boundary: experimentation/checkpoint

SYSTEM = "experimentation"
NODE = "experimentation/checkpoint"
OWNS = "checkpoint identity, binding and lifecycle"
MUST_NOT_OWN = "artifact content storage"
AUTHORITY = "checkpoint_state"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
