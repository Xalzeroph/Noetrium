# vNext Boundary: execution/workflow

SYSTEM = "execution"
NODE = "execution/workflow"
OWNS = "workflow definitions and orchestration semantics"
MUST_NOT_OWN = "process supervision"
AUTHORITY = "workflow_state"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
