# vNext Boundary: execution/operation

SYSTEM = "execution"
NODE = "execution/operation"
OWNS = "immutable execution command intent plus operation identity, lifecycle and result envelopes"
MUST_NOT_OWN = "failure taxonomy, recovery authority, provider effects or workflow orchestration"
AUTHORITY = "operation_state"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="execution",
    node="execution/operation",
    package_prefix='noetrium_platform.research.execution.operation',
    authority_id="operation_state",
    owns="immutable execution command intent plus operation identity, lifecycle and result envelopes",
    must_not_own="failure taxonomy, recovery authority, provider effects or workflow orchestration",
    api_module='noetrium_platform.research.execution.operation.api',
    runtime_module='noetrium_platform.research.execution.operation.runtime',
    provider_module='noetrium_platform.research.execution.operation.providers',
    composition_module='noetrium_platform.research.execution.operation.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
