# vNext Boundary: scope/hierarchy

SYSTEM = "scope"
NODE = "scope/hierarchy"
OWNS = "parent/child relationships, ancestry, descendants"
MUST_NOT_OWN = "project business fields"
AUTHORITY = "scope_hierarchy"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="scope",
    node="scope/hierarchy",
    package_prefix='noetrium_platform.foundation.scope.hierarchy',
    authority_id="scope_hierarchy",
    owns="parent/child relationships, ancestry, descendants",
    must_not_own="project business fields",
    api_module='noetrium_platform.foundation.scope.hierarchy.api',
    runtime_module='noetrium_platform.foundation.scope.hierarchy.runtime',
    provider_module='noetrium_platform.foundation.scope.hierarchy.providers',
    composition_module='noetrium_platform.foundation.scope.hierarchy.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
