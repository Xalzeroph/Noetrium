# vNext Boundary: experimentation/run

SYSTEM = "experimentation"
NODE = "experimentation/run"
OWNS = "run identity, frozen run contract and run lifecycle"
MUST_NOT_OWN = "server supervision internals"
AUTHORITY = "run_state"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
