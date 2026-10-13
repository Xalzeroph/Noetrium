#!/bin/sh

# Resolve machine-scoped Noetrium state against the primary Git worktree so
# detached/frozen linked worktrees share immutable machine resources by default.
# Explicit operator configuration always wins. Source bundles without Git
# metadata fall back to their own Noetrium root.
noetrium_primary_worktree_root() {
  noetrium_root="$1"
  if command -v git >/dev/null 2>&1; then
    primary_root="$(
      git -C "$noetrium_root" worktree list --porcelain 2>/dev/null \
        | sed -n 's/^worktree //p' \
        | sed -n '1p'
    )"
    if [ -n "$primary_root" ] && [ -d "$primary_root" ]; then
      primary_root="$(CDPATH= cd -- "$primary_root" 2>/dev/null && pwd)" || primary_root=""
      if [ -n "$primary_root" ] && [ -f "$primary_root/deploy/noetrium" ]; then
        printf '%s\n' "$primary_root"
        return 0
      fi
    fi
  fi
  printf '%s\n' "$noetrium_root"
}

noetrium_machine_state_root() {
  noetrium_root="$1"
  if [ -n "${NOETRIUM_MACHINE_STATE_ROOT:-}" ]; then
    printf '%s\n' "$NOETRIUM_MACHINE_STATE_ROOT"
    return 0
  fi
  canonical_root="$(noetrium_primary_worktree_root "$noetrium_root")"
  printf '%s/.noetrium/machine\n' "$canonical_root"
}
