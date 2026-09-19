# vNext Boundary: operator/audit

SYSTEM = "operator"
NODE = "operator/audit"
OWNS = "audit/reporting views across system authorities"
MUST_NOT_OWN = "new durable truth"
AUTHORITY = "operator_audit"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
