# Prompt OS — Round 10

Prompting is treated as compiled, qualified runtime configuration rather than a mutable string.

## Compilation pipeline

```text
Stable Role Spec
 + Typed Dynamic Blocks
 + Role Block Policy
 + Output Schema Digest
 + Frozen Model Identity
 + Decoding Settings
 + Prompt Generation Identity
 -> Budget Check
 -> Compiled Prompt
 -> PromptExecutionContract
 -> Transport
```

### No silent prompt degradation

`PromptBudgetPlanner` measures the exact static/dynamic blocks against the configured context and reserved output budget. If it does not fit, it raises `PromptBudgetExceeded` with a full budget report. It never truncates memory, drops tools, shortens output tokens, swaps models, or silently summarizes context.

### Output contracts

Output schemas are centrally registered and content-digested. Request evidence binds both schema ID and schema digest so an edited schema cannot masquerade as the same prompt generation.

Schema JSON is structurally frozen at `OutputSchemaSpec` construction. Prompt-generation payloads and reconstructed/model-visible request bodies use non-bypassable `Mapping`/tuple values rather than subclasses of mutable `dict`/`list`; even base-class mutators cannot alter a digest-bound cut. Canonical bytes are produced through the platform canonical encoder, and a mutable dict/list is materialized only at the final HTTP transport boundary. The request-build transaction freezes immediately after the body builder returns and the model-request recorder repeats the freeze at its durable authority boundary. Its public ABI accepts only `Mapping[str, JsonInput]` request bodies and `JsonInput` tool schemas, while reconstruction returns immutable JSON authority rather than a mutable `dict`; unsupported Python objects fail closed before publication. Contracts, content-addressed bytes and transport-visible content therefore derive from one immutable JSON cut.

### Durable publication

`DurablePromptRegistry` publishes one write-once generation and atomically replaces one `ACTIVE` pointer. The generation binds prompt text, decoding, role block policies and output schema digests. Loading recomputes both the outer generation hash and each bundle hash.

### Qualification

Canary evidence and outcome lineage remain separate from publication. A candidate prompt can be generated and stored without becoming active. Promotion should require exact model/revision + suite + role qualification; no unqualified fallback prompt is activated automatically.

## Role design v5

- Planner: strict authority hierarchy, one executable next action, verifier-only completion, no hidden CoT requirement.
- Semantic: J_mem-grounded derivation, evidence IDs, minimal representation, no private evaluation evidence.
- Meta: neutral AOR only, fixed structural grammar, one intent or NO_EDIT, no activation/tool/model/prompt authority.
- Diagnostic: separates proven cause/correlation/unknowns and repeats only mechanically authorized recovery.
