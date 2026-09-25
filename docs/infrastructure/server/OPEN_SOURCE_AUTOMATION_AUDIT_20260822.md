# Open-source server/Git automation audit — 2026-08-22

## Scope

Review public implementations relevant to the platform's GitHub publication,
SSH/SCP transport and multi-server lifecycle. The purpose is to improve the
existing persistent system, not to replace its profile-bound composition or
copy a deployment framework wholesale.

## Reviewed implementations

| Project | Relevant pattern | Decision for this platform |
|---|---|---|
| [philiprehberger/shipyard](https://github.com/philiprehberger/shipyard) | immutable release directories, remote lock, upload-before-activation, atomic `current` switch, health-gated promotion, rollback, stable exit classes | Keep as a release-lifecycle reference. Our content-addressed release publisher already verifies the package and atomically renames a staging directory; health-gated experiment activation remains a separate future lifecycle concern. |
| [absolutejs/deploy](https://github.com/absolutejs/deploy) | a narrow target with only `exec`, `upload`, and lifecycle close; idempotent target identity; exclude runtime-only trees such as `node_modules`; explicit timeout and health verification | Confirms the current narrow server ports and the new bridge `node_modules/` boundary. Do not add a broad server locator. |
| [ansible-core SSH connection](https://github.com/ansible/ansible/blob/devel/lib/ansible/plugins/connection/ssh.py) | explicit connection, command and persistent-connection timeouts; public-key/password mechanism controls; batch transfer semantics; configurable transfer method | Our transport isolation is stricter for unattended work: no TTY, no prompt-capable auth, no ControlMaster reuse, and a non-blocking per-server lease. The remaining useful comparison is a first-class SFTP transfer provider, not more retries. |
| [Paramiko SSHClient](https://github.com/paramiko/paramiko/blob/main/paramiko/client.py) | separate connect/banner/auth/channel timeout concepts and explicit host-key policy | Confirms why one outer SSH timeout is insufficient. The current profile-bound OpenSSH route already has connect, command/transfer, keepalive and remote Git watchdog boundaries; any future Paramiko adapter must preserve the same port contract. |
| [Dulwich](https://github.com/jelmer/dulwich) and [git bundle](https://git-scm.com/docs/git-bundle) | local Git object transport without requiring remote GitHub reachability; bundle fetch imports the exact commit graph | Adopted as the default persistent repository-sync transport. The current provider creates/verifies the local exact bundle, uploads it through the managed transfer port, checks the remote base SHA, imports it, and removes the staging file. The remote-Git route remains explicit only. |

## Root-cause comparison

The failed `83246ac` synchronization was not an SSH-authentication prompt:
the new transport lease prevented the concurrent probe, the noninteractive
argv rejected prompt-capable authentication, and the remote Git watchdog
terminated the child. The remaining failure was external route reachability:
remote GitHub HTTPS timed out after about 133 seconds and the checkout stayed
at the prior clean SHA. The ledger correctly required reconciliation.

Therefore the repository-sync improvement is transport selection, not a
larger retry loop:

1. Keep the explicit remote-Git route bounded and fail-closed.
2. Use the controller-local, exact-revision Git-bundle route by default for
   servers whose outbound GitHub route is unavailable.
3. Keep bundle upload, remote import, cleanup and status evidence one explicit
   lifecycle with no untracked residue and no hidden credentials.
4. Preserve the exact SHA/origin/clean-worktree gate and operation
   reconciliation semantics.

## Non-adoptions

- No password/askpass path will be reintroduced.
- No global ControlMaster will be enabled for automation.
- No automatic retry will be added for an effect-uncertain mutation.
- No direct `git pull`, broad shell escape, or untracked runtime dependency
  will become a new authority.
- No deployment framework is vendored merely for convenience.

## Current evidence

- The server transport and repository regression suite previously passed 50
  focused tests and 987 full-suite tests plus 4 subtests.
- The failed new-revision sync was reconciled as `effect_not_applied` from
  remote status: old exact SHA, clean checkout, no staging residue.
- The operation ledger is empty after reconciliation.
