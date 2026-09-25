# Prompt qualification / promotion v24

Durable Prompt OS now has two separate transactions:

1. `stage(generation)` writes a complete immutable candidate generation and **does not** change ACTIVE.
2. `promote(evidence)` atomically changes ACTIVE only after exact qualification evidence is verified.

Promotion evidence binds:

- generation payload SHA-256;
- exact coverage of every prompt bundle digest in that generation;
- role identity;
- Canary Suite digest/evaluator identity;
- exact model resume key, including model/revision/engine/dtype/quantization/context/tokenizer revision;
- complete critical/noncritical canary results;
- objective qualification evidence digest.

A write-once promotion record is fsync'd before the ACTIVE pointer changes. Generation directories and promotion records are immutable. Publication uses a kernel single-writer lease.

There is deliberately no automatic fallback to a previous Prompt generation. If ACTIVE is corrupt or a promoted Prompt later fails a production contract, runtime fails explicitly; an operator must qualify and explicitly promote another generation.
