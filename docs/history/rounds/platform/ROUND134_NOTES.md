# Round 134 — source-local Git bundle synchronization

## Motivation

The first synchronization of `83246ac` demonstrated that the prompt-free SSH
and remote Git watchdog fixes were working, but the Ubuntu host still could
not reach GitHub over HTTPS. Waiting for a bounded remote `git fetch` is safe
but needlessly delays every source publication.

## Open-source collision review

The design was compared with Shipyard's immutable release/health-gated
deployment model, absolutejs/deploy's narrow `exec`/`upload` target, Ansible's
separate SSH/command/transfer boundaries, Paramiko's separate authentication
timeouts, and Dulwich/Git's bundle transport. Only the last one changes the
repository transport; the other patterns confirm boundaries already present
in the platform.

## Implemented

- Added `SSHGitBundleRepositorySynchronizer` under the server lifecycle
  provider boundary.
- The controller validates a clean local checkout, matching GitHub origin and
  exact requested commit, then creates and verifies a temporary Git bundle.
- The bundle is uploaded through the existing profile-bound observed transfer
  port. It is placed at the repository synchronizer's visible staging path,
  so interrupted uploads cannot become invisible residue.
- Remote import rechecks origin, cleanliness and the observed base SHA before
  fetching the bundle, then checks out the exact target SHA and removes the
  bundle with a remote trap.
- `scripts/server_repository_sync.py` now defaults to `--transport bundle`.
  The previous remote GitHub route remains available only as explicit
  `--transport remote-git`.

## Safety properties

- No unattended TTY, password, askpass or ControlMaster path is introduced.
- A failed/uncertain transfer or import remains in the existing operation
  ledger and blocks further mutations until evidence-based reconciliation.
- The exact origin, SHA and clean-worktree gates remain unchanged.
- No automatic retry is added.

## Verification requirement

The exact revision containing this round must be synchronized to Ubuntu using
the new default bundle route, then the server focused transport/repository
regression and full suite must pass. A real bundle synchronization is required
before claiming the route operational.

## Workflow decision

After this bootstrap transport is operational, the managed Ubuntu checkout is
the primary implementation and validation workspace. Platform and project
changes are made there, tested there, and pushed from there. The Windows
checkout is a final synchronization/review copy only; it is not a source of
scientific test evidence.
