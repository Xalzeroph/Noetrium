# vNext Boundary: participant/definition

SYSTEM = "participant"
NODE = "participant/definition"
OWNS = "participant identities and types"
MUST_NOT_OWN = "execution session state"
AUTHORITY = "participant_definition"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
