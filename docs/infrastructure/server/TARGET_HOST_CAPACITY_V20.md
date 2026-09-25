# Target Host Inventory / Capacity v20

No production model placement is inferred from generic host names or public benchmark tables. The deployment host is frozen as a hash-complete `TargetHostInventory` containing:

- allowed CPUs, cgroup quota and NUMA CPU/memory topology;
- GPU UUID/name/VRAM/free VRAM/PCIe/NUMA/compute capability/power limit;
- GPU fabric links and measured/declared bandwidth class;
- physical + cgroup effective memory;
- mount device/filesystem/free bytes/free inodes/reflink capability;
- kernel, Python, Node, Java, NVIDIA driver/CUDA/NVML and serving-engine versions;
- nofile/pid limits and occupied listening ports.

`QualificationCertificate.target_host_fingerprint` must equal this exact inventory digest. Therefore a model qualified on one inventory cannot silently migrate to a changed driver/GPU/cgroup/storage layout.

`ExactCapacityPlanner` combines the exact host inventory, exact `ModelStackSpec` and measured `ResourceEnvelope`. It chooses a topology-local GPU group and CPU set, but never changes tensor parallelism, dtype, quantization, context length, model, engine, prompt or method. Insufficient capacity is an explicit placement error.

The resulting maximum request concurrency is capped at the concurrency already qualified in the certificate. Excess work is queued by admission control rather than running an unqualified overload configuration.
