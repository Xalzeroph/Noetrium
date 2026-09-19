# vNext Boundary: participant/method

SYSTEM = "participant"
NODE = "participant/method"
OWNS = "method participant binding contracts"
MUST_NOT_OWN = "method implementation itself"
AUTHORITY = "method_participant_binding"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
