# Model Serving OS

## Principle

A model server is a managed, evidence-producing state machine. It is not a shell command and it is not identified by a mutable endpoint alone.

## Model-run state machine

```text
NEW -> INVENTORY -> PREPARE -> LOAD -> WARMUP -> READY -> RUNNING
                                                   |
                                                   v
                                              DRAINING
                                                   |
                                                   v
                                               STOPPING -> STOPPED

Any active phase -> FAILED / INTERRUPTED -> RECOVERY_REQUIRED
```

Lifecycle state, endpoint readiness, deployment qualification, and scientific admission are distinct authorities. A healthy HTTP endpoint is not by itself a qualification certificate.

## Exact recovery

Recovery must verify the exact artifact, runtime, deployment generation, process identity, endpoint route, and role canary evidence before resuming unfinished work. Recovery never silently chooses a smaller model, lower precision, shorter context, different engine, different prompt generation, or different revision.
## Frozen model-stack identity

Each serving stack freezes at least:

- model ID and exact revision or artifact digest;
- tokenizer/processor identity where applicable;
- backend implementation and exact package/container identity;
- dtype, quantization, context length, and cache policy;
- tensor/expert/data/pipeline parallel settings;
- scheduler, batching, parser, and tool-call settings;
- runtime environment and native-library closure;
- GPU placement and topology evidence;
- endpoint generation and readiness contract.

The reusable platform does not select a project model. A downstream repository supplies model stacks, roles, prompts, quality requirements, and placement policy through public model/serving contracts.

## Role routing

A deployment may expose one or more logical role identities. Multiple roles may share a frozen model revision or physical replica, but role prompt generations, request traces, endpoint placement, rate limits, and decision authority remain independently auditable.

Role routing must not create an implicit fallback path. A route change is a new deployment generation or an explicitly governed reconciliation event.
## Performance qualification

Measure at minimum:

- cold/warm load time;
- TTFT and TPOT distributions;
- input/output throughput;
- concurrency-versus-latency curves;
- queue delay and continuous-batch occupancy;
- prefix/KV-cache effectiveness and preemption;
- GPU memory, utilization, power, and temperature;
- collective-communication time for multi-device stacks;
- CPU/NUMA locality, host-memory pressure, and I/O pressure;
- endpoint, schema, and exact-token canary failures.

A faster degraded stack does not outrank a slower stack that satisfies the frozen correctness contract. Qualification must exercise workload-shaped requests rather than benchmark headlines alone.

## Multi-GPU policy

Parallelism is a qualified deployment property, not a heuristic integer. Before launch the platform should verify divisibility/model-architecture constraints, visible-device identity, memory headroom, topology, collective support, and the exact backend/runtime combination. Runtime evidence then confirms the devices actually used.

Concrete GPU assignments and project-specific replica layouts belong downstream. The upstream owns only the contracts, observation, planning, evidence, and fail-closed admission machinery.
