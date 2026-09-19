# vNext Boundary: participant/session

SYSTEM = "participant"
NODE = "participant/session"
OWNS = "participant session identity and lifecycle contract"
MUST_NOT_OWN = "server/process implementation"
AUTHORITY = "participant_session"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
