# vNext Boundary: experimentation/run/control

SYSTEM = "experimentation"
NODE = "experimentation/run/control"
OWNS = "external run lifecycle effect coordination and read-only RunMachine projections"
MUST_NOT_OWN = "run phase, control generation, checkpoint head, Machine Journal truth, operator product intents or server supervision internals"
AUTHORITY = "run_machine"
