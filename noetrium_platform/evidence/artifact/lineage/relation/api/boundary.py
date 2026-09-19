# vNext Boundary: artifact/lineage/relation

SYSTEM = "artifact"
NODE = "artifact/lineage/relation"
OWNS = "immutable artifact lineage edge identity"
MUST_NOT_OWN = "scientific result semantics"
AUTHORITY = "artifact_lineage_edge"


from noetrium_platform.foundation.kernel.kernel.leaf_contract import SystemLeafContract


CONTRACT = SystemLeafContract(
    system_id="artifact",
    node="artifact/lineage/relation",
    package_prefix='noetrium_platform.evidence.artifact.lineage.relation',
    authority_id="artifact_lineage_edge",
    owns="immutable artifact lineage edge identity",
    must_not_own="scientific result semantics",
    api_module='noetrium_platform.evidence.artifact.lineage.relation.api',
    runtime_module='noetrium_platform.evidence.artifact.lineage.relation.runtime',
    provider_module='noetrium_platform.evidence.artifact.lineage.relation.providers',
    composition_module='noetrium_platform.evidence.artifact.lineage.relation.composition',
)


def contract() -> SystemLeafContract:
    return CONTRACT
