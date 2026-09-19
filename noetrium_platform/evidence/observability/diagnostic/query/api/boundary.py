# vNext Boundary: observability/diagnostic/query

SYSTEM = "observability"
NODE = "observability/diagnostic/query"
OWNS = "operator/debug query language over observation sources"
MUST_NOT_OWN = "source mutation"
AUTHORITY = "diagnostic_query"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="observability",
    node="observability/diagnostic/query",
    package_prefix='noetrium_platform.evidence.observability.diagnostic.query',
    authority_id="diagnostic_query",
    owns="operator/debug query language over observation sources",
    must_not_own="source mutation",
    api_module='noetrium_platform.evidence.observability.diagnostic.query.api',
    runtime_module='noetrium_platform.evidence.observability.diagnostic.query.runtime',
    provider_module='noetrium_platform.evidence.observability.diagnostic.query.providers',
    composition_module='noetrium_platform.evidence.observability.diagnostic.query.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
