# Telemetry OS

## Strategy

Record broadly; derive and select later. Raw observations are immutable evidence. Dashboards/aggregates are disposable views.

## Metric families

### LLM
request/attempt latency, queue wait, input/output/reasoning/cached tokens where provided, finish reason, HTTP status, contract repair, response parse, retry sleep, endpoint/circuit state.

### Model serving
TTFT, TPOT, tokens/s, active/queued requests, batch size, KV-cache usage, prefix-cache hit, preemptions, scheduler delay, speculative acceptance when enabled, engine-specific counters.

### GPU/host
GPU utilization/memory/power/temperature/clock, PCIe/NVLink/NCCL where available, CPU utilization/context switches, cgroup pressure, RSS, file descriptors, disk bytes/latency, WAL sizes, inode/free-space, network bytes/errors.

### Runtime
operation latency/status, event backlog, metric recorder lag, queue depths, worker/process lifecycle, leases, checkpoint duration/size, recovery duration/attempts.

### Environment
action latency/result, verifier latency, effect certainty, reconnects, bridge/server lifecycle, observation sizes.

### Method
recall/query planning/retrieval latency, node hits, candidate generation, evolution stage latency, acceptance results, architecture generation, materialization costs. Method-specific metrics stay namespaced under the plugin.

### Prompt
bundle use, contract errors, repair rate, canary pass rate, outcome lineage, token/latency by bundle.

## Dimension discipline

Do not put unbounded IDs such as request_id directly in high-volume metric dimensions. IDs belong in events/traces. Metrics use bounded dimensions; exact IDs are joined through trace/span/request records.
