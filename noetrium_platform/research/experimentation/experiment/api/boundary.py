# vNext Boundary: experimentation/experiment

SYSTEM = "experimentation"
NODE = "experimentation/experiment"
OWNS = "experiment definitions, variants and experiment lifecycle"
MUST_NOT_OWN = "runtime process state"
AUTHORITY = "experiment_state"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
