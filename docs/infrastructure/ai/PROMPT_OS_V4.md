# Prompt OS v4 — Typed Prompt Compilation

## Core change

Prompt text and runtime context are separated.

```text
Stable role prompt
+ typed dynamic blocks
+ output contract
+ immutable model identity
= exact Prompt Request Contract
```

The dynamic blocks are not arbitrary strings from random modules. Each role has an allowlist and required set.

### Planner may receive

- task
- verified state
- tool catalog
- memory context
- prior verified outcome

### Semantic may receive

- memory-grounded evidence/context
- task context when required

### Meta may receive

- neutral Architecture Observation Report only

It must not receive the downstream environment tool catalog, raw private evaluator evidence, candidate labels or task outcome shortcuts.

### Diagnostic may receive

- structured failure evidence only

## Why this improves prompt quality

1. Stable instructions no longer compete with ad-hoc concatenated text.
2. Role authority is enforced before transport.
3. Dynamic context size is bounded per block instead of globally truncated at random.
4. Each block carries a source digest, so a bad output can be reproduced from the exact context assembly.
5. Canary qualification binds the exact prompt digest and evaluator suite digest.
6. Outcome lineage records associations but never upgrades them into causal claims automatically.
