# vNext Boundary: experimentation/branch

SYSTEM = "experimentation"
NODE = "experimentation/branch"
OWNS = "run branching and branch lineage"
MUST_NOT_OWN = "generic artifact lineage"
AUTHORITY = "branch_state"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="experimentation",
    node="experimentation/branch",
    package_prefix='noetrium_platform.research.experimentation.branch',
    authority_id="branch_state",
    owns="run branching and branch lineage",
    must_not_own="generic artifact lineage",
    api_module='noetrium_platform.research.experimentation.branch.api',
    runtime_module='noetrium_platform.research.experimentation.branch.runtime',
    provider_module='noetrium_platform.research.experimentation.branch.providers',
    composition_module='noetrium_platform.research.experimentation.branch.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
