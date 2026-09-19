# vNext Boundary: execution/command

SYSTEM = "execution"
NODE = "execution/command"
OWNS = 'immutable typed command intent and routing contracts evaluated by Execution'
MUST_NOT_OWN = 'durable execution truth, operation lifecycle, Machine state or provider effects'
AUTHORITY = "command_intent"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="execution",
    node="execution/command",
    package_prefix='noetrium_platform.research.execution.command',
    authority_id="command_intent",
    owns='immutable typed command intent and routing contracts evaluated by Execution',
    must_not_own='durable execution truth, operation lifecycle, Machine state or provider effects',
    api_module='noetrium_platform.research.execution.command.api',
    runtime_module='noetrium_platform.research.execution.command.runtime',
    provider_module='noetrium_platform.research.execution.command.providers',
    composition_module='noetrium_platform.research.execution.command.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
