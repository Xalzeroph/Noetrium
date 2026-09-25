# Telemetry Runtime Contract

Every important runtime stage must declare a triplet:

```text
STAGE_STARTED
STAGE_SUCCEEDED
STAGE_FAILED
```

and every declared event must have at least one real emitter binding.

This closes a common observability failure mode: documentation/registry says an event exists, but no source path ever emits it.

Recommended major stages:

- study lifecycle
- task lifecycle
- decision cycle
- prompt compile/request build
- LLM queue/admission/attempt/parse
- environment action/verify/reconcile
- memory query plan/snapshot/retrieval
- evolution eligibility/diagnosis/synthesis/compile/evaluation/adoption
- materialization evidence/transform/write
- checkpoint create/verify/restore
- model inventory/prepare/load/warmup/ready/run/drain/stop/recovery

Stage events carry exact IDs; metrics carry bounded dimensions. This lets operators use metrics to identify a hot region, then jump through trace/span/request IDs to exact forensic evidence.
