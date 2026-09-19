# vNext Boundary: artifact/reference

SYSTEM = "artifact"
NODE = "artifact/reference"
OWNS = "references, aliases and cross-system artifact pointers"
MUST_NOT_OWN = "content mutation"
AUTHORITY = "artifact_reference"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="artifact",
    node="artifact/reference",
    package_prefix='noetrium_platform.evidence.artifact.reference',
    authority_id="artifact_reference",
    owns="references, aliases and cross-system artifact pointers",
    must_not_own="content mutation",
    api_module='noetrium_platform.evidence.artifact.reference.api',
    runtime_module='noetrium_platform.evidence.artifact.reference.runtime',
    provider_module='noetrium_platform.evidence.artifact.reference.providers',
    composition_module='noetrium_platform.evidence.artifact.reference.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
