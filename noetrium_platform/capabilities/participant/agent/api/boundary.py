# vNext Boundary: participant/agent

SYSTEM = "participant"
NODE = "participant/agent"
OWNS = "agent participant contracts and provider-independent agent identity"
MUST_NOT_OWN = "model serving lifecycle"
AUTHORITY = "agent_identity"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
