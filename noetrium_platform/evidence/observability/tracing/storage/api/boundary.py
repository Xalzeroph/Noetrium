# vNext Boundary: observability/tracing/storage

SYSTEM = "observability"
NODE = "observability/tracing/storage"
OWNS = "trace/span storage backends"
MUST_NOT_OWN = "trace identity semantics"
AUTHORITY = "trace_storage"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="observability",
    node="observability/tracing/storage",
    package_prefix='noetrium_platform.evidence.observability.tracing.storage',
    authority_id="trace_storage",
    owns="trace/span storage backends",
    must_not_own="trace identity semantics",
    api_module='noetrium_platform.evidence.observability.tracing.storage.api',
    runtime_module='noetrium_platform.evidence.observability.tracing.storage.runtime',
    provider_module='noetrium_platform.evidence.observability.tracing.storage.providers',
    composition_module='noetrium_platform.evidence.observability.tracing.storage.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
