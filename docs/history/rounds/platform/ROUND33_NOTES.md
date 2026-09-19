# Round 33 — Prompt/LLM Request Trace

- Added exact per-request Prompt/LLM stage tracing: creation, compile, queue, dispatch, headers, first byte/token, completion, parse, schema validation, outcome link, failure.
- Each trace point is joinable through the full `ExecutionContext` and may be persisted to the raw telemetry lake without sampling.
- Prompt compilation now exposes exact per-block characters/bytes/source digest plus total compiled size.
- `PromptExecutionContract` binds those diagnostics through a block-stats digest and compiled-size fields.
- Trace summaries emit online latency metrics while the raw lake retains request IDs and stage detail outside low-cardinality labels.
- No hidden retry, alternate prompt, model substitution, context truncation or quality-reducing path was added.
