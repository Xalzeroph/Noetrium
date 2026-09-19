# vNext Boundary: environment/instance/readiness

SYSTEM = "environment"
NODE = "environment/instance/readiness"
OWNS = "environment readiness observations/contract"
MUST_NOT_OWN = "authoritative process health"
AUTHORITY = "environment_readiness"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="environment",
    node="environment/instance/readiness",
    package_prefix='noetrium_platform.capabilities.environment.instance.readiness',
    authority_id="environment_readiness",
    owns="environment readiness observations/contract",
    must_not_own="authoritative process health",
    api_module='noetrium_platform.capabilities.environment.instance.readiness.api',
    runtime_module='noetrium_platform.capabilities.environment.instance.readiness.runtime',
    provider_module='noetrium_platform.capabilities.environment.instance.readiness.providers',
    composition_module='noetrium_platform.capabilities.environment.instance.readiness.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
