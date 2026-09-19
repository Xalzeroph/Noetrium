from noetrium_platform.research.execution.capability.api import (
    CapabilityLifetime, CapabilityRegistration, CapabilityTypeMismatch, RegistrationKey,
)
from noetrium_platform.research.execution.capability.runtime import ScopedRegistrationRuntime


def test_typed_capability_registration_enforces_contract_and_lifetime():
    scope = ScopedRegistrationRuntime("operation:1")
    contract = CapabilityRegistration(RegistrationKey("capability", "write"), str,
                                      owner_id="participant:1", lifetime=CapabilityLifetime.PARTICIPANT_SESSION)
    handle = scope.register_typed(contract, "route")
    with scope.acquire_typed(contract) as value:
        assert value == "route"
    handle.close()


def test_typed_capability_rejects_object_bag_drift():
    scope = ScopedRegistrationRuntime("operation:1")
    contract = CapabilityRegistration(RegistrationKey("capability", "write"), str, owner_id="participant:1")
    try:
        scope.register_typed(contract, object())
    except CapabilityTypeMismatch:
        pass
    else:
        raise AssertionError("typed capability must reject value type drift")
