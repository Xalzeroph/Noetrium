# vNext Boundary: model/catalog/revision

SYSTEM = "model"
NODE = "model/catalog/revision"
OWNS = "versioned model revision identity"
MUST_NOT_OWN = "mutable serving state"
AUTHORITY = "model_revision"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="model",
    node="model/catalog/revision",
    package_prefix='noetrium_platform.capabilities.model.catalog.revision',
    authority_id="model_revision",
    owns="versioned model revision identity",
    must_not_own="mutable serving state",
    api_module='noetrium_platform.capabilities.model.catalog.revision.api',
    runtime_module='noetrium_platform.capabilities.model.catalog.revision.runtime',
    provider_module='noetrium_platform.capabilities.model.catalog.revision.providers',
    composition_module='noetrium_platform.capabilities.model.catalog.revision.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
