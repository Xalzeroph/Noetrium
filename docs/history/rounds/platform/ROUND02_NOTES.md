# Round 02 — Evidence Integrity / Fast Triage

Added:

- tamper-evident hash-chained event/failure/mutation ledgers;
- disposable SQLite forensic index with WAL and busy timeout;
- direct object locator and authoritative last-writer query;
- `MutationRecord` with state/version/digest/context ownership;
- exact Prompt Request Contract binding request body, prompt bundle and immutable model identity;
- metric-cardinality audit that rejects unbounded request/trace/task IDs as metric labels;
- persistent atomic Model Supervisor state file;
- executable forensics demo.

Design intent:

Raw evidence is authoritative and append-only. SQLite is only an acceleration layer. If the index is damaged, it should be rebuilt from verified ledgers rather than becoming a second source of truth.
