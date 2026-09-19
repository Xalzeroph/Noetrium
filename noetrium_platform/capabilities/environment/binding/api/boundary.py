# vNext Boundary: environment/binding

SYSTEM = "environment"
NODE = "environment/binding"
OWNS = "binding environment specs to scopes/runs/participants"
MUST_NOT_OWN = "artifact storage"
AUTHORITY = "environment_binding"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="environment",
    node="environment/binding",
    package_prefix='noetrium_platform.capabilities.environment.binding',
    authority_id="environment_binding",
    owns="binding environment specs to scopes/runs/participants",
    must_not_own="artifact storage",
    api_module='noetrium_platform.capabilities.environment.binding.api',
    runtime_module='noetrium_platform.capabilities.environment.binding.runtime',
    provider_module='noetrium_platform.capabilities.environment.binding.providers',
    composition_module='noetrium_platform.capabilities.environment.binding.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
