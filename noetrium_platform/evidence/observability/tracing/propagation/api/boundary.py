# vNext Boundary: observability/tracing/propagation

SYSTEM = "observability"
NODE = "observability/tracing/propagation"
OWNS = "cross-process trace propagation contracts"
MUST_NOT_OWN = "trace storage"
AUTHORITY = "trace_propagation"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="observability",
    node="observability/tracing/propagation",
    package_prefix='noetrium_platform.evidence.observability.tracing.propagation',
    authority_id="trace_propagation",
    owns="cross-process trace propagation contracts",
    must_not_own="trace storage",
    api_module='noetrium_platform.evidence.observability.tracing.propagation.api',
    runtime_module='noetrium_platform.evidence.observability.tracing.propagation.runtime',
    provider_module='noetrium_platform.evidence.observability.tracing.propagation.providers',
    composition_module='noetrium_platform.evidence.observability.tracing.propagation.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
