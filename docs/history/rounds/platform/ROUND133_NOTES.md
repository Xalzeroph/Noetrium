# Round 133 — hard-bound remote Git lifetime

## Reproduction

After SSH multiplexing and transport-lease isolation were installed, a final
no-TTY synchronization still stayed in `started`. A concurrent read-only status
probe correctly failed fast with `ServerTransportBusy`, proving the local
transport lease was working. Once the synchronization ended, its stderr was:

```text
error: RPC failed; curl 28 Failed to connect to github.com port 443 after 133272 ms: Connection timed out
fatal: expected flush after ref listing
```

The repository remained at the previous SHA, clean and without staging
residue. The operation was reconciled as `effect_not_applied` from that
read-only evidence.

## Root cause

The outer SSH deadline (`SSH_REPOSITORY_TIMEOUT_SECONDS=1800`) bounded only the
SSH client process. Git's libcurl connection path did not honor the expected
`http.connectTimeout=15` in this server route, so `git fetch` could occupy the
remote shell for more than two minutes before returning. The prior fixes
prevented hidden password prompts and concurrent authentication races, but did
not bound the remote Git child itself.

## Structural correction

- `ServerConnectionProfile` now owns `git_transport_timeout_seconds`, loaded
  from `SSH_GIT_TIMEOUT_SECONDS`, defaulting to 120 seconds and required not to
  exceed the outer repository timeout.
- The repository synchronizer preflights `timeout` through the profile-bound
  remote PATH, then wraps both `git fetch` and `git clone` with
  `timeout --foreground --signal=TERM --kill-after=10s`.
- Git terminal prompts, askpass and interactive credential helpers remain
  disabled; the watchdog is an independent child-process boundary, not a
  retry or quality downgrade.

## Verification

- Fixed revision synchronization completed in **7.6 seconds** on Ubuntu.
- Focused server regression: **50 passed in 0.43s**.
- Full server regression: **987 passed, 1 warning, 4 subtests passed in
  101.57s**.
- Final operation ledger: **empty**; server repository exact, clean, no
  staging residue.
