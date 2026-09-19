# vNext Boundary: environment/resolution

SYSTEM = "environment"
NODE = "environment/resolution"
OWNS = "resolve logical environment requirements to concrete instance plan"
MUST_NOT_OWN = "process lifecycle"
AUTHORITY = "environment_resolution"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="environment",
    node="environment/resolution",
    package_prefix='noetrium_platform.capabilities.environment.resolution',
    authority_id="environment_resolution",
    owns="resolve logical environment requirements to concrete instance plan",
    must_not_own="process lifecycle",
    api_module='noetrium_platform.capabilities.environment.resolution.api',
    runtime_module='noetrium_platform.capabilities.environment.resolution.runtime',
    provider_module='noetrium_platform.capabilities.environment.resolution.providers',
    composition_module='noetrium_platform.capabilities.environment.resolution.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
