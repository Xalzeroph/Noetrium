#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
BOOTSTRAP_IMAGE="${NOETRIUM_BOOTSTRAP_IMAGE:-noetrium/environment-builder:local}"
DOCKER_CLI_IMAGE="${NOETRIUM_DOCKER_CLI_IMAGE:-docker:27-cli}"
WORK_ROOT="${NOETRIUM_BUILD_WORK_ROOT:-$ROOT/.noetrium/environment-images}"
BOOTSTRAP_MANAGED_LABEL="io.noetrium.bootstrap-managed"
BOOTSTRAP_MANAGED_VALUE="control-v1"
BOOTSTRAP_CHILD_LABEL="io.noetrium.bootstrap-child"
BOOTSTRAP_CHILD_VALUE="qualification-v1"
OWNER_PID_LABEL="io.noetrium.bootstrap-owner-pid"
OWNER_BOOT_LABEL="io.noetrium.bootstrap-owner-boot"
OWNER_START_LABEL="io.noetrium.bootstrap-owner-start"
BOOT_ID="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || printf 'unknown')"
OWNER_START="$(awk '{print $22}' "/proc/$$/stat" 2>/dev/null || printf 'unknown')"
BOOTSTRAP_CONTAINER_NAME="noetrium-bootstrap-$(printf '%s' "$BOOT_ID" | tr -cd '[:alnum:]' | cut -c1-12)-$$"
BOOTSTRAP_ACTIVE=0

bootstrap_owner_alive() {
  pid="$1"
  boot="$2"
  start="$3"
  [ "$boot" = "$BOOT_ID" ] || return 1
  [ "$pid" -gt 0 ] 2>/dev/null || return 1
  [ -r "/proc/$pid/stat" ] || return 1
  current_start="$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null || true)"
  [ -n "$current_start" ] && [ "$current_start" = "$start" ]
}

bootstrap_container_absent() {
  id="$1"
  remaining="$(docker ps -aq --no-trunc --filter "id=$id")" || {
    echo "Unable to prove bootstrap container absence: $id" >&2
    return 2
  }
  [ -z "$remaining" ]
}

remove_bootstrap_container_exact() {
  id="$1"
  if docker rm -f "$id" >/dev/null 2>&1; then
    return 0
  fi
  if bootstrap_container_absent "$id"; then
    return 0
  fi
  echo "Failed to remove bootstrap container and absence is unproven: $id" >&2
  return 1
}

reconcile_bootstrap_containers() {
  ids="$(docker ps -aq --no-trunc --filter "label=$BOOTSTRAP_MANAGED_LABEL=$BOOTSTRAP_MANAGED_VALUE")"
  [ -n "$ids" ] || return 0
  for id in $ids; do
    if ! metadata="$(docker inspect --format '{{index .Config.Labels "io.noetrium.bootstrap-owner-pid"}}|{{index .Config.Labels "io.noetrium.bootstrap-owner-boot"}}|{{index .Config.Labels "io.noetrium.bootstrap-owner-start"}}|{{.State.Running}}' "$id" 2>/dev/null)"; then
      if bootstrap_container_absent "$id"; then
        continue
      fi
      echo "Unable to inspect live bootstrap container: $id" >&2
      return 1
    fi
    old_ifs="$IFS"
    IFS='|'
    set -- $metadata
    IFS="$old_ifs"
    owner_pid="${1:-}"
    owner_boot="${2:-}"
    owner_start="${3:-}"
    running="${4:-false}"
    if [ "$running" = "true" ] && bootstrap_owner_alive "$owner_pid" "$owner_boot" "$owner_start"; then
      continue
    fi
    remove_bootstrap_container_exact "$id"
  done
}


reconcile_bootstrap_children() {
  ids="$(docker ps -aq --no-trunc --filter "label=$BOOTSTRAP_CHILD_LABEL=$BOOTSTRAP_CHILD_VALUE")"
  [ -n "$ids" ] || return 0
  for id in $ids; do
    if ! metadata="$(docker inspect --format '{{index .Config.Labels "io.noetrium.bootstrap-owner-pid"}}|{{index .Config.Labels "io.noetrium.bootstrap-owner-boot"}}|{{index .Config.Labels "io.noetrium.bootstrap-owner-start"}}|{{.State.Running}}' "$id" 2>/dev/null)"; then
      if bootstrap_container_absent "$id"; then
        continue
      fi
      echo "Unable to inspect live bootstrap child container: $id" >&2
      return 1
    fi
    old_ifs="$IFS"
    IFS='|'
    set -- $metadata
    IFS="$old_ifs"
    owner_pid="${1:-}"
    owner_boot="${2:-}"
    owner_start="${3:-}"
    running="${4:-false}"
    if [ "$running" = "true" ] && bootstrap_owner_alive "$owner_pid" "$owner_boot" "$owner_start"; then
      continue
    fi
    remove_bootstrap_container_exact "$id"
  done
}

cleanup_owned_bootstrap_children() {
  if ! ids="$(docker ps -aq --no-trunc \
    --filter "label=$BOOTSTRAP_CHILD_LABEL=$BOOTSTRAP_CHILD_VALUE" \
    --filter "label=$OWNER_PID_LABEL=$$" \
    --filter "label=$OWNER_BOOT_LABEL=$BOOT_ID" \
    --filter "label=$OWNER_START_LABEL=$OWNER_START" 2>/dev/null)"; then
    echo "Unable to enumerate owned bootstrap child containers during cleanup." >&2
    return 1
  fi
  [ -n "$ids" ] || return 0
  failed=0
  for id in $ids; do
    remove_bootstrap_container_exact "$id" || failed=1
  done
  return "$failed"
}

cleanup_owned_bootstrap_container() {
  if ! ids="$(docker ps -aq --no-trunc \
    --filter "label=$BOOTSTRAP_MANAGED_LABEL=$BOOTSTRAP_MANAGED_VALUE" \
    --filter "label=$OWNER_PID_LABEL=$$" \
    --filter "label=$OWNER_BOOT_LABEL=$BOOT_ID" \
    --filter "label=$OWNER_START_LABEL=$OWNER_START" 2>/dev/null)"; then
    echo "Unable to enumerate owned bootstrap container during cleanup." >&2
    return 1
  fi
  [ -n "$ids" ] || return 0
  failed=0
  for id in $ids; do
    remove_bootstrap_container_exact "$id" || failed=1
  done
  return "$failed"
}

bootstrap_cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  cleanup_failed=0
  cleanup_owned_bootstrap_children || cleanup_failed=1
  if [ "$BOOTSTRAP_ACTIVE" = "1" ]; then
    cleanup_owned_bootstrap_container || cleanup_failed=1
    BOOTSTRAP_ACTIVE=0
  fi
  if [ "$cleanup_failed" = "1" ]; then
    echo "Bootstrap cleanup did not prove physical convergence." >&2
    [ "$status" -ne 0 ] || status=1
  fi
  exit "$status"
}

run_bootstrap_container() {
  BOOTSTRAP_ACTIVE=1
  trap bootstrap_cleanup EXIT HUP INT TERM
  # Keep the command inside an if so set -e cannot bypass the normal
  # convergence path on a non-zero Docker result.
  # shellcheck disable=SC2086
  if docker run --rm --init --restart no \
    --name "$BOOTSTRAP_CONTAINER_NAME" \
    --label "$BOOTSTRAP_MANAGED_LABEL=$BOOTSTRAP_MANAGED_VALUE" \
    --label "$OWNER_PID_LABEL=$" \
    --label "$OWNER_BOOT_LABEL=$BOOT_ID" \
    --label "$OWNER_START_LABEL=$OWNER_START" \
    "$@"; then
    status=0
  else
    status=$?
  fi

  # --rm is an optimization, not convergence evidence. A daemon restart can
  # make command completion ambiguous after the physical container already
  # stopped or before Docker completed auto-removal. Re-observe/remove every
  # object owned by this exact PID + boot + process-start generation before
  # dropping the launcher-side ownership bit.
  cleanup_failed=0
  cleanup_owned_bootstrap_children || cleanup_failed=1
  cleanup_owned_bootstrap_container || cleanup_failed=1
  BOOTSTRAP_ACTIVE=0
  trap - EXIT HUP INT TERM
  if [ "$cleanup_failed" = "1" ]; then
    echo "Bootstrap completion did not prove physical convergence." >&2
    [ "$status" -ne 0 ] || status=1
  fi
  return "$status"
}

command -v docker >/dev/null 2>&1 || {
  echo "Noetrium environment bootstrap requires Docker on the host." >&2
  exit 127
}

docker info >/dev/null 2>&1 || {
  echo "Noetrium environment bootstrap cannot reach the active Docker daemon." >&2
  exit 1
}

# Reap only Noetrium bootstrap containers whose exact host owner generation is
# gone. Live concurrent launchers are preserved. This closes the SIGKILL/SSH
# disconnect orphan case that Docker --rm alone cannot prove away.
reconcile_bootstrap_children
reconcile_bootstrap_containers

# Resolve the daemon endpoint from DOCKER_HOST first and otherwise from the
# active Docker context. This keeps the host contract at Docker itself rather
# than assuming a rootful /var/run/docker.sock installation.
DAEMON_HOST="${DOCKER_HOST:-}"
if [ -z "$DAEMON_HOST" ]; then
  DAEMON_HOST="$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
fi
[ -n "$DAEMON_HOST" ] || DAEMON_HOST="unix:///var/run/docker.sock"

case "$DAEMON_HOST" in
  unix://*)
    DAEMON_SOCKET="${DAEMON_HOST#unix://}"
    test -S "$DAEMON_SOCKET" || {
      echo "Docker daemon socket is unavailable: $DAEMON_SOCKET" >&2
      exit 1
    }
    DAEMON_ARGS="-v $DAEMON_SOCKET:$DAEMON_SOCKET -e DOCKER_HOST=$DAEMON_HOST"
    ;;
  tcp://*)
    # Plain TCP endpoints need no host mount. TLS endpoints intentionally stay
    # explicit because forwarding client certificates is deployment policy.
    if [ "${DOCKER_TLS_VERIFY:-}" = "1" ]; then
      echo "TLS Docker endpoints require an explicit bootstrap integration; refusing to copy host credentials implicitly." >&2
      exit 1
    fi
    DAEMON_ARGS="-e DOCKER_HOST=$DAEMON_HOST"
    ;;
  *)
    echo "Unsupported Docker daemon endpoint for containerized bootstrap: $DAEMON_HOST" >&2
    echo "Use a unix:// or non-TLS tcp:// Docker endpoint." >&2
    exit 1
    ;;
esac

mkdir -p "$WORK_ROOT"
WORK_ROOT="$(CDPATH= cd -- "$WORK_ROOT" && pwd)"

# Linked Git worktrees store only a .git pointer inside the checkout. The
# pointed-to metadata lives under the primary repository and must be visible at
# the same absolute path inside the bootstrap container. Resolve it without
# requiring host Git or Python so the host contract remains Docker + POSIX sh.
GIT_METADATA_ARGS=""
if [ -f "$ROOT/.git" ]; then
  GITDIR="$(sed -n 's/^gitdir: //p' "$ROOT/.git")"
  [ -n "$GITDIR" ] || {
    echo "Linked worktree .git pointer is invalid: $ROOT/.git" >&2
    exit 1
  }
  case "$GITDIR" in
    /*) ;;
    *) GITDIR="$ROOT/$GITDIR" ;;
  esac
  GITDIR="$(CDPATH= cd -- "$GITDIR" && pwd -P)"
  GIT_METADATA_ROOT="$GITDIR"
  if [ -f "$GITDIR/commondir" ]; then
    COMMONDIR="$(cat "$GITDIR/commondir")"
    case "$COMMONDIR" in
      /*) GIT_METADATA_ROOT="$COMMONDIR" ;;
      *) GIT_METADATA_ROOT="$GITDIR/$COMMONDIR" ;;
    esac
    GIT_METADATA_ROOT="$(CDPATH= cd -- "$GIT_METADATA_ROOT" && pwd -P)"
  fi
  GIT_METADATA_ARGS="-v $GIT_METADATA_ROOT:$GIT_METADATA_ROOT:ro"
fi

if [ "${NOETRIUM_BOOTSTRAP_REUSE:-0}" = "1" ]; then
  docker image inspect "$BOOTSTRAP_IMAGE" >/dev/null 2>&1 || {
    echo "Requested bootstrap reuse but image is missing: $BOOTSTRAP_IMAGE" >&2
    exit 1
  }
else
  docker build \
    --build-arg "DOCKER_CLI_IMAGE=$DOCKER_CLI_IMAGE" \
    --tag "$BOOTSTRAP_IMAGE" \
    --file "$ROOT/deploy/bootstrap/Dockerfile" \
    "$ROOT"
fi

# The bootstrap talks to the host Docker daemon. Preserve host absolute paths
# inside the control-plane container so daemon-side build contexts and Compose
# bind mounts resolve to the same files. Source stays read-only; only the
# dedicated build/runtime root is writable. Git's safe-directory exception is
# scoped to this exact read-only checkout; it is needed because the disposable
# container's uid can differ from the checkout owner on CI or rootless hosts.
COMMON_ARGS="$DAEMON_ARGS $GIT_METADATA_ARGS -v $ROOT:$ROOT:ro -w $ROOT -e PYTHONDONTWRITEBYTECODE=1 -e NOETRIUM_BOOTSTRAP_OWNER_PID=$$ -e NOETRIUM_BOOTSTRAP_OWNER_BOOT=$BOOT_ID -e NOETRIUM_BOOTSTRAP_OWNER_START=$OWNER_START -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=$ROOT"

if [ "${1:-}" = "control" ]; then
  shift
  [ "$#" -gt 0 ] || {
    echo "Noetrium control requires a Python entrypoint." >&2
    exit 2
  }
  mkdir -p "$WORK_ROOT/control"
  CONTROL_ENV_FILE="${NOETRIUM_CONTROL_ENV_FILE:-}"
  if [ -z "$CONTROL_ENV_FILE" ] && [ -f "$ROOT/deploy/.env" ]; then
    CONTROL_ENV_FILE="$ROOT/deploy/.env"
  fi
  if [ -n "$CONTROL_ENV_FILE" ]; then
    test -f "$CONTROL_ENV_FILE" || {
      echo "Noetrium control env file does not exist: $CONTROL_ENV_FILE" >&2
      exit 1
    }
    # shellcheck disable=SC2086
    run_bootstrap_container --entrypoint python3 $COMMON_ARGS \
      --env-file "$CONTROL_ENV_FILE" \
      -v "$WORK_ROOT:$WORK_ROOT" \
      -e NOETRIUM_CONTROL_STATE_ROOT="$WORK_ROOT/control" \
      "$BOOTSTRAP_IMAGE" "$@"
    exit $?
  fi
  # shellcheck disable=SC2086
  run_bootstrap_container --entrypoint python3 $COMMON_ARGS \
    -v "$WORK_ROOT:$WORK_ROOT" \
    -e NOETRIUM_CONTROL_STATE_ROOT="$WORK_ROOT/control" \
    "$BOOTSTRAP_IMAGE" "$@"
  exit $?
fi

if [ "${1:-}" = "build" ]; then
  # shellcheck disable=SC2086
  run_bootstrap_container $COMMON_ARGS \
    -v "$WORK_ROOT:$WORK_ROOT" \
    "$BOOTSTRAP_IMAGE" \
    "$@" \
    --work-root "$WORK_ROOT" \
    --output "$WORK_ROOT/environment-image-build.json"
  exit $?
fi

# shellcheck disable=SC2086
run_bootstrap_container $COMMON_ARGS \
  "$BOOTSTRAP_IMAGE" \
  "$@"
exit $?
