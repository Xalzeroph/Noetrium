# Server Infrastructure

The server subsystem is a reusable platform control plane for identifying remote hosts, loading explicit connection profiles, executing bounded commands, transferring files, managing persistent sessions, projecting diagnostics, and recording mutation/observation operations.

It does **not** own a deployment fleet. Concrete hostnames, addresses, users, credentials, remote filesystem layouts, accelerator assignments, and project deployment roles belong in downstream or operator-local configuration.

## Public boundary

The platform owns typed server identity, profile parsing, transport/session contracts, operation journals, repository/release transport primitives, capacity observations, and diagnostic projections.

Profiles are supplied explicitly through environment-bound or ignored local files. The generic example is [`../../../configs/server_profiles/server.example.env`](../../../configs/server_profiles/server.example.env).
## Operational rules

- Never commit passwords, private keys, tokens, or machine-local credentials.
- Never infer a remote path when a profile contract requires it explicitly.
- Bound command, transfer, repository, and session operations with separate budgets.
- Distinguish read-only observation from mutation in the operation journal.
- Preserve unresolved/uncertain external effects until reconciliation establishes their state.
- Keep fleet membership outside the reusable platform repository.

See [`SERVER_CONNECTIONS.md`](SERVER_CONNECTIONS.md) for the generic connection contract and [`SERVER_TMUX_RUNTIME.md`](SERVER_TMUX_RUNTIME.md) for persistent-session semantics.
