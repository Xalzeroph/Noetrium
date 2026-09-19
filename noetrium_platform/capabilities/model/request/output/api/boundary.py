# vNext Boundary: model/request/output

SYSTEM = "model"
NODE = "model/request/output"
OWNS = "response envelope and response artifact references"
MUST_NOT_OWN = "business metric semantics"
AUTHORITY = "request_output"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="model",
    node="model/request/output",
    package_prefix='noetrium_platform.capabilities.model.request.output',
    authority_id="request_output",
    owns="response envelope and response artifact references",
    must_not_own="business metric semantics",
    api_module='noetrium_platform.capabilities.model.request.output.api',
    runtime_module='noetrium_platform.capabilities.model.request.output.runtime',
    provider_module='noetrium_platform.capabilities.model.request.output.providers',
    composition_module='noetrium_platform.capabilities.model.request.output.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
