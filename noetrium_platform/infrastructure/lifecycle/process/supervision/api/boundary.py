# vNext Boundary: runtime/process/supervision

SYSTEM = "runtime"
NODE = "runtime/process/supervision"
OWNS = "process health/reconcile loops"
MUST_NOT_OWN = "durable runtime history storage"
AUTHORITY = "process_supervision"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="runtime",
    node="runtime/process/supervision",
    package_prefix='noetrium_platform.infrastructure.lifecycle.process.supervision',
    authority_id="process_supervision",
    owns="process health/reconcile loops",
    must_not_own="durable runtime history storage",
    api_module='noetrium_platform.infrastructure.lifecycle.process.supervision.api',
    runtime_module='noetrium_platform.infrastructure.lifecycle.process.supervision.runtime',
    provider_module='noetrium_platform.infrastructure.lifecycle.process.supervision.providers',
    composition_module='noetrium_platform.infrastructure.lifecycle.process.supervision.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
