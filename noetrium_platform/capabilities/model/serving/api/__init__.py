"""Stable contracts for live model serving.

Only identities, immutable manifests/state, qualification semantics, and narrow ports
are exported here. Concrete supervisors, recovery runners, planners, and storage
backends live in runtime/providers and are wired by composition.
"""

from .admission import (
    ModelAdmissionClosed,
    ModelAdmissionLeasePort,
    ModelAdmissionPort,
    ModelAdmissionRegistryPort,
    ModelAdmissionTimeout,
)
from .deployment import (
    FrozenDeploymentIdentity,
    FrozenDeploymentSet,
    FrozenRoleAssignment,
    RuntimeQualificationPublication,
    RuntimeQualificationPublisherPort,
)
from .heartbeat import ServiceHeartbeat
from .host_verification import (
    HostInventoryReceipt,
    HostResourceDelta,
    build_host_inventory_receipt,
    compare_host_inventory_receipts,
)
from .host_verification_ports import HostInventoryEvidenceStorePort, HostInventoryProvider
from .inventory import (
    CPUInventory,
    CPUNode,
    GPUFabricLink,
    GPUInventory,
    HostInventory,
    HostLimits,
    MemoryInventory,
    MountInventory,
    RuntimeInventory,
)
from .placement import DeploymentPlacement, GpuPlacementPolicyPort
from .qualification import (
    PerformanceSample,
    QualificationDecision,
    QualificationEvidence,
    QualificationPolicy,
    ResourceQualificationMeasurements,
    RoleCanaryResult,
    evaluate_qualification,
)
from .qualified_deployment import (
    QualificationCertificate,
    QualifiedDeploymentManifest,
    ResourceEnvelope,
    RoleModelAssignment,
    RoleModelManifest,
)
from .recovery import RecoveryPlan, RecoveryStep
from .recovery_observer import (
    DurableRecoveryObserverFailureSink,
    DurableRecoveryObserverPort,
    RecoveryObserverFailure,
)
from .recovery_ports import DurableRecoveryStorePort
from .recovery_state import (
    DurableRecoveryAttempt,
    DurableRecoveryPhase,
    RecoveryResumeDecision,
    begin_recovery_step,
    complete_recovery_step,
    decide_resume,
    fail_recovery_step,
    new_recovery_attempt,
    recovery_plan_digest,
    succeed_recovery,
)
from .runtime_canary import (
    RuntimeCanaryContract,
    RuntimeCanaryEvidence,
    RuntimeCanaryProbe,
    evaluate_runtime_canary_contract,
)
from .runtime_canary_ports import RuntimeCanaryEvidenceStorePort
from .runtime_qualification import RuntimeQualificationReceipt, build_runtime_qualification_receipt
from .runtime_qualification_ports import RuntimeQualificationEvidenceStorePort
from .state import ModelPhase, ModelRunState
from .supervisor_ports import ModelSupervisorStateStorePort

__all__ = [
    "CPUInventory", "CPUNode", "DeploymentPlacement", "GpuPlacementPolicyPort", "DurableRecoveryAttempt",
    "DurableRecoveryObserverFailureSink", "DurableRecoveryObserverPort", "DurableRecoveryPhase",
    "DurableRecoveryStorePort", "FrozenDeploymentIdentity", "FrozenDeploymentSet",
    "FrozenRoleAssignment", "GPUFabricLink", "GPUInventory", "HostInventory",
    "HostInventoryEvidenceStorePort", "HostInventoryProvider", "HostInventoryReceipt", "HostLimits",
    "HostResourceDelta", "MemoryInventory", "ModelAdmissionClosed", "ModelAdmissionLeasePort",
    "ModelAdmissionPort", "ModelAdmissionRegistryPort", "ModelAdmissionTimeout", "ModelPhase",
    "ModelRunState", "ModelSupervisorStateStorePort",
    "MountInventory", "PerformanceSample",
    "QualificationCertificate", "QualificationDecision", "QualificationEvidence", "QualificationPolicy", "ResourceQualificationMeasurements",
    "QualifiedDeploymentManifest", "RecoveryObserverFailure", "RecoveryPlan", "RecoveryResumeDecision",
    "RecoveryStep", "ResourceEnvelope", "RoleCanaryResult", "RoleModelAssignment", "RoleModelManifest",
    "RuntimeCanaryContract", "RuntimeCanaryEvidence", "RuntimeCanaryEvidenceStorePort",
    "RuntimeCanaryProbe",
    "RuntimeInventory", "RuntimeQualificationEvidenceStorePort",
    "RuntimeQualificationPublication", "RuntimeQualificationPublisherPort", "RuntimeQualificationReceipt",
    "ServiceHeartbeat", "begin_recovery_step", "build_host_inventory_receipt",
    "build_runtime_qualification_receipt", "compare_host_inventory_receipts", "complete_recovery_step",
    "decide_resume", "evaluate_qualification", "evaluate_runtime_canary_contract",
    "fail_recovery_step", "new_recovery_attempt",
    "recovery_plan_digest", "succeed_recovery",
]
