# vNext Boundary: operator/query/search

SYSTEM = "operator"
NODE = "operator/query/search"
OWNS = "human-readable search and filtering over read-side projections"
MUST_NOT_OWN = "authoritative writes"
AUTHORITY = "operator_search"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="operator",
    node="operator/query/search",
    package_prefix='noetrium_platform.product.operator.query.search',
    authority_id="operator_search",
    owns="human-readable search and filtering over read-side projections",
    must_not_own="authoritative writes",
    api_module='noetrium_platform.product.operator.query.search.api',
    runtime_module='noetrium_platform.product.operator.query.search.runtime',
    provider_module='noetrium_platform.product.operator.query.search.providers',
    composition_module='noetrium_platform.product.operator.query.search.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
