# vNext Boundary: model/catalog/family

SYSTEM = "model"
NODE = "model/catalog/family"
OWNS = "model family identity and metadata"
MUST_NOT_OWN = "revision deployment state"
AUTHORITY = "model_family"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="model",
    node="model/catalog/family",
    package_prefix='noetrium_platform.capabilities.model.catalog.family',
    authority_id="model_family",
    owns="model family identity and metadata",
    must_not_own="revision deployment state",
    api_module='noetrium_platform.capabilities.model.catalog.family.api',
    runtime_module='noetrium_platform.capabilities.model.catalog.family.runtime',
    provider_module='noetrium_platform.capabilities.model.catalog.family.providers',
    composition_module='noetrium_platform.capabilities.model.catalog.family.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
