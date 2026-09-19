# vNext Boundary: observability/tracing/context

SYSTEM = "observability"
NODE = "observability/tracing/context"
OWNS = "trace/span context creation and attachment"
MUST_NOT_OWN = "business operation state"
AUTHORITY = "trace_context"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="observability",
    node="observability/tracing/context",
    package_prefix='noetrium_platform.evidence.observability.tracing.context',
    authority_id="trace_context",
    owns="trace/span context creation and attachment",
    must_not_own="business operation state",
    api_module='noetrium_platform.evidence.observability.tracing.context.api',
    runtime_module='noetrium_platform.evidence.observability.tracing.context.runtime',
    provider_module='noetrium_platform.evidence.observability.tracing.context.providers',
    composition_module='noetrium_platform.evidence.observability.tracing.context.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
