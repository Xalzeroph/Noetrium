from __future__ import annotations

from dataclasses import dataclass

from ..api.qualified_deployment import QualificationCertificate
from ..api.inventory import HostInventory
from ..api.placement import GpuPlacementPolicyPort
from noetrium_platform.capabilities.model.stack.api import ModelStackSpec
from .placement_policy import ExactFabricPlacementPolicy


class HostQualificationMismatch(RuntimeError): pass
class PlacementCapacityError(RuntimeError): pass


@dataclass(frozen=True, slots=True)
class DeploymentRequirements:
    deployment_id: str
    service_port: int
    storage_path: str
    host_memory_headroom_bytes: int = 8*1024**3
    gpu_memory_headroom_bytes: int = 2*1024**3
    minimum_nofile: int = 65536


@dataclass(frozen=True, slots=True)
class ExactCapacityPlan:
    deployment_id: str
    host_identity_digest: str
    host_snapshot_digest: str
    model_stack_digest: str
    qualification_digest: str
    gpu_uuids: tuple[str,...]
    cpu_ids: tuple[int,...]
    numa_nodes: tuple[int,...]
    service_port: int
    storage_path: str
    max_admitted_concurrency: int
    required_host_memory_bytes: int
    required_gpu_memory_bytes_per_device: int


class ExactCapacityPlanner:
    """Plan only the already-qualified stack; placement policy is an injected port."""

    def __init__(self, placement_policy: GpuPlacementPolicyPort | None = None) -> None:
        self._placement_policy = placement_policy or ExactFabricPlacementPolicy()

    def plan(self,host:HostInventory,stack:ModelStackSpec,cert:QualificationCertificate,req:DeploymentRequirements)->ExactCapacityPlan:
        host_identity=host.identity_digest(); host_snapshot=host.snapshot_digest(); sd=stack.digest()
        if cert.target_host_identity_digest!=host_identity: raise HostQualificationMismatch("qualification certificate was measured on a different host/runtime identity")
        if cert.model_stack_digest!=sd: raise HostQualificationMismatch("qualification certificate does not match model stack")
        if req.service_port in host.listening_ports: raise PlacementCapacityError(f"service port already in use: {req.service_port}")
        if host.limits.nofile_soft<req.minimum_nofile: raise PlacementCapacityError("nofile limit below frozen service requirement")
        mount=next((m for m in host.mounts if req.storage_path==m.path or req.storage_path.startswith(m.path.rstrip('/')+'/')),None)
        if mount is None: raise PlacementCapacityError("storage path not covered by inventory")
        required_host=cert.resource_envelope.peak_host_memory_bytes+req.host_memory_headroom_bytes
        if host.memory.effective_available_bytes<required_host: raise PlacementCapacityError("insufficient effective host memory for qualified stack")
        required_gpu=cert.resource_envelope.peak_gpu_memory_bytes_per_device+req.gpu_memory_headroom_bytes
        candidates=tuple(g for g in host.gpus if g.free_memory_bytes>=required_gpu)
        if len(candidates)<stack.tensor_parallel: raise PlacementCapacityError("insufficient qualified GPU VRAM; stack may not be degraded")
        group=self._placement_policy.select(host,candidates,stack.tensor_parallel)
        if len(group) != stack.tensor_parallel or len({g.uuid for g in group}) != len(group):
            raise PlacementCapacityError("GPU placement policy returned an invalid group")
        candidate_ids={g.uuid for g in candidates}
        if any(g.uuid not in candidate_ids for g in group):
            raise PlacementCapacityError("GPU placement policy escaped the qualified candidate set")
        numa=tuple(sorted({g.numa_node for g in group if g.numa_node is not None}))
        allowed=set(host.cpu.allowed_cpu_ids)
        cpu_ids=tuple(sorted(cpu for node in host.cpu.numa_nodes if not numa or node.numa_node in numa for cpu in node.cpu_ids if cpu in allowed))
        if not cpu_ids: cpu_ids=tuple(sorted(allowed))
        if not cpu_ids: raise PlacementCapacityError("no allowed CPUs available")
        return ExactCapacityPlan(req.deployment_id,host_identity,host_snapshot,sd,cert.digest(),tuple(g.uuid for g in group),cpu_ids,numa,req.service_port,req.storage_path,cert.resource_envelope.max_qualified_concurrency,required_host,required_gpu)
