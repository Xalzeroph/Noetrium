# Managed runtime shutdown order

Shutdown preserves evidence before releasing infrastructure.

- Stop admission/controllers before releasing their owned resources.
- Flush journal-linked receipts before evidence-producing services disappear.
- Observability shutdown cannot delete authoritative run state.
- Cleanup errors are aggregated and surfaced; silent partial shutdown is forbidden.
