# vNext Boundary: environment/specification/digest

SYSTEM = "environment"
NODE = "environment/specification/digest"
OWNS = "exact environment specification identity and digest"
MUST_NOT_OWN = "resource resolution"
AUTHORITY = "environment_digest"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="environment",
    node="environment/specification/digest",
    package_prefix='noetrium_platform.capabilities.environment.specification.digest',
    authority_id="environment_digest",
    owns="exact environment specification identity and digest",
    must_not_own="resource resolution",
    api_module='noetrium_platform.capabilities.environment.specification.digest.api',
    runtime_module='noetrium_platform.capabilities.environment.specification.digest.runtime',
    provider_module='noetrium_platform.capabilities.environment.specification.digest.providers',
    composition_module='noetrium_platform.capabilities.environment.specification.digest.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
