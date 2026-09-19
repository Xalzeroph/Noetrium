"""Runtime view of the canonical environment state-machine contracts.

State-machine value semantics and the transition port are owned by the
environment API. Runtime code consumes this forwarding surface only; it must
not define a second contract implementation.
"""

from noetrium_platform.capabilities.environment.api.state_machine import (
    JsonInput,
    JsonMutableValue,
    JsonScalar,
    JsonValue,
    StateMachineDynamicsIdentity,
    StateMachineDynamicsPort,
    StateMachineEnvironmentSpec,
    StateTransition,
    freeze_json_mapping,
    thaw_json,
    thaw_json_mapping,
)

__all__ = [
    "JsonScalar",
    "JsonInput",
    "JsonMutableValue",
    "JsonValue",
    "StateMachineDynamicsIdentity",
    "StateMachineDynamicsPort",
    "StateMachineEnvironmentSpec",
    "StateTransition",
    "freeze_json_mapping",
    "thaw_json",
    "thaw_json_mapping",
]
