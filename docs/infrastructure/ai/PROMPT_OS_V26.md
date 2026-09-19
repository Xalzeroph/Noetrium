# Prompt OS v26

The Prompt OS treats prompts as immutable executable contracts, not mutable strings.

## Stable role contracts

`planner.v6`, `semantic.v6`, `meta.v6`, and `diagnostic.v3` define only stable authority and output behavior. Task state, memory, tools and reports are supplied as separately typed dynamic blocks.

## Authority hierarchy

### Planner

`Verified present state / verified action result > admitted historical memory > prior plans/model text`.

### Semantic

Only memory-authorized admitted evidence can produce materializable semantic memory. Conflicting grounded evidence remains explicitly conflicting rather than being rewritten into false certainty.

### Meta

Only a neutral Architecture Observation Report is visible. Runtime tuning, resource pressure and isolated failures cannot be promoted into structural edits without persistent structural evidence.

### Diagnostic

The prompt cannot invent causal edges or recovery authority. `Operation failed` and `external effect unknown` are separate facts; unknown effect requires reconcile/observe before replay.

## Quality policy

There is no prompt fallback or hidden context truncation. Candidate prompts require qualification and explicit promotion through Durable Prompt OS; a bad active generation fails explicitly rather than silently reverting.
