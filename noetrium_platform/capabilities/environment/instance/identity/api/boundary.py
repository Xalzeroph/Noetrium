# vNext Boundary: environment/instance/identity

SYSTEM = "environment"
NODE = "environment/instance/identity"
OWNS = "environment instance identity and provenance"
MUST_NOT_OWN = "host process lifecycle"
AUTHORITY = "environment_instance_identity"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="environment",
    node="environment/instance/identity",
    package_prefix='noetrium_platform.capabilities.environment.instance.identity',
    authority_id="environment_instance_identity",
    owns="environment instance identity and provenance",
    must_not_own="host process lifecycle",
    api_module='noetrium_platform.capabilities.environment.instance.identity.api',
    runtime_module='noetrium_platform.capabilities.environment.instance.identity.runtime',
    provider_module='noetrium_platform.capabilities.environment.instance.identity.providers',
    composition_module='noetrium_platform.capabilities.environment.instance.identity.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
