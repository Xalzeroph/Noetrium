# vNext Boundary: model/deployment/closure

SYSTEM = "model"
NODE = "model/deployment/closure"
OWNS = "exact deployment closure across model, stack, runtime and artifact identities"
MUST_NOT_OWN = "server runtime health"
AUTHORITY = "deployment_closure"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="model",
    node="model/deployment/closure",
    package_prefix='noetrium_platform.capabilities.model.deployment.closure',
    authority_id="deployment_closure",
    owns="exact deployment closure across model, stack, runtime and artifact identities",
    must_not_own="server runtime health",
    api_module='noetrium_platform.capabilities.model.deployment.closure.api',
    runtime_module='noetrium_platform.capabilities.model.deployment.closure.runtime',
    provider_module='noetrium_platform.capabilities.model.deployment.closure.providers',
    composition_module='noetrium_platform.capabilities.model.deployment.closure.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
