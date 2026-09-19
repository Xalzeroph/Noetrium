# Round 27 — Prompt Publication and Forensic Index Authority Decomposition

## Prompt publication

The former publication module mixed two different durable authorities. It is now decomposed into:

- `PromptGenerationStore`: sole owner of immutable generation bytes; it has no ACTIVE pointer;
- `PromptPromotionStore`: sole owner of qualification validation, promotion records and atomic ACTIVE pointer replacement;
- `DurablePromptRegistry`: composition only.

Staging cannot activate a generation. Promotion cannot stage/modify generation bytes.

## Forensic index

The disposable SQLite projection is now decomposed into:

- `ForensicIndexDB`: schema and connection policy;
- `ForensicIndexReader`: pure read/query model;
- `ForensicIndexWriter`: sole projection writer;
- `ForensicIndex`: small composition surface.

A read-only index never initializes schema and physically has no writer instance.

## Architecture result

- pytest: 135 / 135 PASS
- Architecture Gate: PASS
- Silent-Failure Audit: PASS
- No-Degradation Audit: PASS
- package cycles: 0
- forbidden physical dependencies: 0

The old monolithic Prompt publication and Forensic index modules no longer appear as the dominant architecture hotspots. Static prompt/catalog source still scores high by line count; those are data-definition density rather than transaction/control-flow coupling.
