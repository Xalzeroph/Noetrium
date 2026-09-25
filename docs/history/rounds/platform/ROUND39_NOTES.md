# Round 39 — Prompt Publication Transactions

- Split generation encoding/verification from durable generation storage.
- Split promotion evidence validation from ACTIVE-pointer I/O.
- Centralized fsync + atomic file/directory publication helpers.
- Stale staging directories fail closed instead of being silently overwritten.
- Prompt generation and promotion remain independently authorized: staging never changes ACTIVE; promotion cannot mutate generation bytes.
- This is an observability/maintainability refactor; prompt text, qualification semantics and frozen model identity are unchanged.
