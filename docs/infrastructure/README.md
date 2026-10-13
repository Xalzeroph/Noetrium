# Infrastructure

Noetrium infrastructure owns physical realization beneath research semantics: compute admission, endpoints, processes, services, containers, model serving, environment instances, host observation, and lifecycle recovery.

The governing rule is **share immutable realization; isolate mutable scientific state**.

## Boundaries

Research code declares requirements. Infrastructure chooses and proves a realization through the owning authorities. Downstream projects do not select GPU IDs, ports, service PIDs, Docker generations, or provider fallback paths as hidden scientific state.

Physical ownership uses leases, generations, fencing, and reconciliation. A stale process or controller cannot reclaim resources after ownership changes. External host workloads are treated as external facts; Noetrium does not kill unrelated work merely to create capacity.

## Deployment

Use the unified launcher on Linux servers:

```bash
./deploy/noetrium infra doctor
./deploy/noetrium infra env list
./deploy/noetrium infra docker status
./deploy/noetrium research preflight
./deploy/noetrium run
```

For the complete operational model, including Docker-first deployment, environment isolation, shared model serving, scheduling, shutdown, and crash recovery, read [`../architecture/RUNTIME_AND_DEPLOYMENT.md`](../architecture/RUNTIME_AND_DEPLOYMENT.md).
