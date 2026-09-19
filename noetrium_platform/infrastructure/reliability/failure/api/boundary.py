# vNext Boundary: reliability/failure

SYSTEM = "reliability"
NODE = "reliability/failure"
OWNS = "failure taxonomy, envelopes, fingerprints and semantic versions"
MUST_NOT_OWN = "diagnostic UI and operator policy"
AUTHORITY = "failure_authority"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
