# vNext Boundary: environment/specification/schema

SYSTEM = "environment"
NODE = "environment/specification/schema"
OWNS = "environment requirement schema and canonical forms"
MUST_NOT_OWN = "environment instance lifecycle"
AUTHORITY = "environment_schema"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="environment",
    node="environment/specification/schema",
    package_prefix='noetrium_platform.capabilities.environment.specification.schema',
    authority_id="environment_schema",
    owns="environment requirement schema and canonical forms",
    must_not_own="environment instance lifecycle",
    api_module='noetrium_platform.capabilities.environment.specification.schema.api',
    runtime_module='noetrium_platform.capabilities.environment.specification.schema.runtime',
    provider_module='noetrium_platform.capabilities.environment.specification.schema.providers',
    composition_module='noetrium_platform.capabilities.environment.specification.schema.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
