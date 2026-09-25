"""Cross-domain Environment ↔ Participant capability composition.

Environment owns environment semantics. Participant owns the generic capability ABI.
This outer composition package binds the two without either sibling authority importing
the other.
"""

from .action import EnvironmentSessionCapabilityAdapter, environment_action_capability_payload
from .branch import (
    EnvironmentBranchCapabilityBinding,
    environment_branch_action_spec,
    environment_fork_action_payload,
    environment_replay_action_payload,
)
from .query import EnvironmentQueryCapabilityBinding, environment_query_capability_payload
from .reset import EnvironmentResetCapabilityBinding, environment_reset_capability_payload

__all__ = [
    "EnvironmentBranchCapabilityBinding",
    "EnvironmentQueryCapabilityBinding",
    "EnvironmentResetCapabilityBinding",
    "EnvironmentSessionCapabilityAdapter",
    "environment_action_capability_payload",
    "environment_branch_action_spec",
    "environment_fork_action_payload",
    "environment_query_capability_payload",
    "environment_replay_action_payload",
    "environment_reset_capability_payload",
]
