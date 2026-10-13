from __future__ import annotations

from noetrium_platform.evidence.observability.telemetry.metric.api import MetricDefinition, MetricKind


def definitions() -> tuple[MetricDefinition, ...]:
    C=MetricKind.COUNTER; G=MetricKind.GAUGE; H=MetricKind.HISTOGRAM
    return (
        MetricDefinition('gpu.memory.clock',G,'mhz',('gpu',),'GPU memory clock'),
        MetricDefinition('gpu.memory.reserved',G,'bytes',('gpu', 'model_service'),'GPU reserved memory'),
        MetricDefinition('gpu.memory.used',G,'bytes',('gpu', 'model_service'),'GPU memory usage'),
        MetricDefinition('gpu.nvlink.rx',C,'bytes',('gpu', 'link'),'NVLink receive bytes'),
        MetricDefinition('gpu.nvlink.tx',C,'bytes',('gpu', 'link'),'NVLink transmit bytes'),
        MetricDefinition('gpu.pcie.rx',C,'bytes',('gpu',),'PCIe receive bytes'),
        MetricDefinition('gpu.pcie.tx',C,'bytes',('gpu',),'PCIe transmit bytes'),
        MetricDefinition('gpu.power',G,'watts',('gpu', 'model_service'),'GPU board power'),
        MetricDefinition('gpu.sm.clock',G,'mhz',('gpu',),'GPU SM clock'),
        MetricDefinition('gpu.temperature',G,'celsius',('gpu', 'model_service'),'GPU temperature'),
        MetricDefinition('gpu.utilization',G,'ratio',('gpu', 'model_service'),'GPU utilization'),
        MetricDefinition('host.cpu.throttled',C,'seconds',('host',),'cgroup CPU throttled time'),
        MetricDefinition('host.cpu.utilization',G,'ratio',('host', 'scope'),'Host/cgroup CPU utilization'),
        MetricDefinition('host.disk.free',G,'bytes',('host', 'mount'),'Free disk bytes'),
        MetricDefinition('host.inodes.free',G,'count',('host', 'mount'),'Free inodes'),
        MetricDefinition('host.io.read',C,'bytes',('host', 'device'),'Read bytes'),
        MetricDefinition('host.io.read_latency',H,'seconds',('host', 'device'),'Read latency'),
        MetricDefinition('host.io.write',C,'bytes',('host', 'device'),'Write bytes'),
        MetricDefinition('host.io.write_latency',H,'seconds',('host', 'device'),'Write latency'),
        MetricDefinition('host.load',G,'ratio',('host', 'window'),'Normalized host load'),
        MetricDefinition('host.memory.pressure',G,'ratio',('host',),'Host/cgroup memory pressure'),
        MetricDefinition('host.memory.used',G,'bytes',('host', 'scope'),'Host/cgroup memory used'),
        MetricDefinition('host.swap.used',G,'bytes',('host',),'Swap usage'),
        MetricDefinition('resource.cpu.assigned',G,'count',('scope',),'Assigned CPUs'),
        MetricDefinition('resource.gpu.assigned',G,'count',('scope',),'Assigned GPUs'),
        MetricDefinition('resource.lease.active',G,'count',('resource_class',),'Active resource leases'),
        MetricDefinition('resource.lease.wait',H,'seconds',('resource_class',),'Resource lease wait'),
        MetricDefinition('resource.memory.reserved',G,'bytes',('scope',),'Reserved memory'),
    )
