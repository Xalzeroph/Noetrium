# Round 131 — unattended server transport boundary

## Problem

Two repository synchronization attempts and a read-only probe were launched
through the interactive SSH path. The target server accepts password
authentication, while the profile had no declared key or agent. Because the
provider captured subprocess output, OpenSSH's password prompt was invisible;
the operation appeared to hang. A second mutating caller could additionally
wait on the server mutation lock without a deadline.

## Root cause

The transport API already distinguished `interactive=False` from
`interactive=True`, but automation entry points still surfaced and used the
latter as a password workaround. The mutation lock also used a blocking kernel
lock, so a concurrent retry had no stable failure boundary.

## Change

- Health, repository, release, runtime, session-lifecycle and status entry
  points force `interactive=False`.
- Non-interactive SSH/SCP arguments explicitly disable password and
  keyboard-interactive authentication, set `BatchMode`, reject unknown host
  keys, limit connection attempts and enable bounded keepalives.
- The only TTY route is `server_session attach`.
- Per-server mutation locks are non-blocking and expose
  `ServerMutationBusy`; observations remain usable while a mutation is in
  flight.
- The first post-fix retry also found a distinct GitHub HTTPS timeout. The
  repository synchronizer now disables Git terminal prompts and applies an
  independent connect/low-speed deadline to fetch and clone.
- Added regression tests for exact argv and concurrent-lock failure.

## Verification contract

The repaired revision must be synchronized to Ubuntu using the configured
non-interactive SSH key/agent. A missing key must produce a fast structured
authentication result; it must never wait for a password prompt.
