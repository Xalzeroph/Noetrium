# vNext Boundary: reliability/recovery

SYSTEM = "reliability"
NODE = "reliability/recovery"
OWNS = "recovery plans, exact replay/reconcile and recovery lifecycle"
MUST_NOT_OWN = "provider storage internals"
AUTHORITY = "recovery_authority"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
