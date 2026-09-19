# vNext Boundary: operator/command

SYSTEM = "operator"
NODE = "operator/command"
OWNS = "operator command intent and command result contracts"
MUST_NOT_OWN = "domain command execution"
AUTHORITY = "operator_commands"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
