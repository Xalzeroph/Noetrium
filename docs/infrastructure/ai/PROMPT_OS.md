# Prompt OS

## Objective

Prompts are versioned executable research artifacts, not loose strings scattered through Python files.

## Prompt bundle identity

A bundle freezes:

- prompt ID/version/role
- exact system text
- ordered dynamic blocks and block schemas
- output contract schema
- model family/model revision
- decoding parameters
- allowed tools/capabilities
- compiler version
- complete bundle digest

Runtime reconstructs the bundle identity from the actual request before transport. Any mismatch is a contract error, not a repairable model-output error.

## Four prompt roles

### Planner
Optimized for grounded next-step planning. It must privilege verified state over memory and never self-certify completion.

### Semantic
Optimized for evidence-grounded derivation. Every derived claim should be traceable to admitted `J_mem` evidence.

### Meta
Optimized for neutral architecture diagnosis and exactly one bounded structural intent. It has no activation, evidence-write, environment or arbitrary-code authority.

### Diagnostic
Only summarizes already-structured evidence for an operator. It must separate proven cause from correlation and unknowns. It cannot hide lower-level failure codes.

## Prompt improvement loop

```text
candidate prompt generation
→ static contract audit
→ adversarial canaries
→ role-specific structured-output tests
→ shadow/offline replay where scientifically valid
→ matched live qualification
→ atomic generation publication
→ outcome lineage analysis
```

Prompt optimization must never silently happen mid-confirmatory run. A promoted prompt is a new immutable generation.

## What to record per request

- prompt bundle digest
- request/body hash
- model/revision/engine endpoint
- exact decoding values
- task/cycle/step
- input token count
- output token count
- queue wait
- attempt latency
- parse/contract latency
- finish reason
- repair attempt identity
- response envelope identity
- action/result linkage
