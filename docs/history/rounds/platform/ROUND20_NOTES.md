# Round 20 — Target Host Inventory and Exact Capacity

- Rich target-host inventory schema and immutable digest.
- Qualification certificate now has a target capable of representing NUMA/GPU fabric/cgroup/storage/runtime identity in full.
- Exact placement checks port, nofile, host memory and per-GPU measured memory envelope.
- GPU selection favors high fabric connectivity and NUMA locality without changing the model stack.
- CPU affinity is derived from selected GPU NUMA nodes and allowed cpuset.
- Maximum admitted concurrency is the measured qualified maximum, never an automatically enlarged or degraded configuration.
