# Managed runtime evidence aggregation

Distributed evidence is derived from journal-linked facts.

- Aggregation keys by canonical run/trial/effect identity.
- Worker-local summaries are not authoritative evidence.
- Duplicate receipts are detected by effect identity.
- Missing receipts keep results incomplete rather than silently imputing success.
