# Round 132 — server transport isolation and prompt-free Git

## Symptom

A no-TTY repository synchronization and a later synchronization could remain
inside the local SSH process while the remote `git fetch` waited. A second
read-only repository probe was also able to enter the same authentication
boundary and appear stuck instead of reporting that the server was busy.

## Root cause

The SSH provider had a profile option for `ControlMaster` reuse but applied it
to automated commands as well as the explicit operator TTY path. Therefore a
local control socket could be owned by a prompt-capable process. The operation
journal serialized mutations only; observations bypassed that boundary and
could create a second SSH authentication attempt. Finally,
`GIT_TERMINAL_PROMPT=0` did not by itself close askpass and interactive
credential-helper paths inside remote Git.

## Structural correction

- Automated SSH/SCP commands force `ControlMaster=no` and `ControlPath=none`,
  and restrict authentication negotiation to public-key transport. The
  configured control path is honored only for explicit interactive operator
  attach.
- The journal now exposes a non-blocking per-server `transport_lock`. Every
  automated SSH/SCP command acquires it before spawning a local transport
  process. A concurrent observation or mutation fails with a typed
  `ServerTransportBusy` instead of entering a shared authentication channel.
- Mutations retain the separate mutation lock and reconciliation gate; the
  lock order is transport then mutation for all mutation call sites.
- Repository synchronization exports terminal/askpass-off switches and sets
  `credential.interactive=false` in both fetch and clone.

## Verification contract

The revision must be synchronized to Ubuntu with no pending operation
reconciliation, then pass the focused server transport, operation-ledger and
repository-sync tests. The full server suite must remain green. The expected
result is fail-fast typed busy behavior for a concurrent read probe and no
automated argv containing `ControlMaster=auto` or a configured
`ControlPath`.

## Actual verification

- The first focused run exposed one incomplete SCP download argv branch. The
  failure was reconciled as `effect_not_applied` after a read-only repository
  status showed the exact target SHA, a clean checkout and no staging residue.
- After the download branch was completed, the fixed SHA synchronized to
  Ubuntu without a prompt or hang.
- Focused server regression: **40 passed in 0.38s**.
- Full server regression: **987 passed, 1 warning, 4 subtests passed in
  100.97s**.
- Final operation ledger: **no pending operations**. The server checkout is
  at the fixed SHA, clean, and has no staging residue.
