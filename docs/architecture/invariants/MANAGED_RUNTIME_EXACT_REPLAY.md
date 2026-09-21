# Managed runtime exact replay

Exact replay is a journal-driven execution mode, not a best-effort rerun.

- Exact replay may consume recorded typed effects but must not silently invoke live providers.
- Missing required receipts fail closed.
- Runtime placement, replica count, and worker identity cannot change replay identity.
- A deliberate live re-execution is a new attempt and must be labeled as such.
