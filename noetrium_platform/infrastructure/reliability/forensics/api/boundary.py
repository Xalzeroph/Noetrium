# vNext Boundary: reliability/forensics

SYSTEM = "reliability"
NODE = "reliability/forensics"
OWNS = "durable evidence bundles, causal evidence and forensic indexes"
MUST_NOT_OWN = "business result semantics"
AUTHORITY = "forensic_authority"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
