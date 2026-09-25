# Round 24 — Prompt Qualification / Explicit Promotion

- Removed direct durable publish-and-activate path.
- Staging is non-activating.
- Promotion requires exact per-bundle qualification coverage and exact model identity.
- Promotion evidence and active-pointer mutation are durable/atomic and single-writer.
- No runtime automatic Prompt rollback/fallback.
