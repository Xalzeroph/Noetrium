#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
BOOTSTRAP_IMAGE="${NOETRIUM_BOOTSTRAP_IMAGE:-noetrium/environment-builder:local}"
DOCKER_CLI_IMAGE="${NOETRIUM_DOCKER_CLI_IMAGE:-docker:27-cli}"
WORK_ROOT="${NOETRIUM_BUILD_WORK_ROOT:-$ROOT/.noetrium/environment-images}"

command -v docker >/dev/null 2>&1 || {
  echo "Noetrium environment bootstrap requires Docker on the host." >&2
  exit 127
}

docker info >/dev/null 2>&1 || {
  echo "Noetrium environment bootstrap cannot reach the active Docker daemon." >&2
  exit 1
}

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

docker build \
  --build-arg "DOCKER_CLI_IMAGE=$DOCKER_CLI_IMAGE" \
  --tag "$BOOTSTRAP_IMAGE" \
  --file "$ROOT/deploy/bootstrap/Dockerfile" \
  "$ROOT"

# The bootstrap talks to the host Docker daemon. Preserve host absolute paths
# inside the control-plane container so daemon-side build contexts and Compose
# bind mounts resolve to the same files. Source stays read-only; only the
# dedicated build/runtime root is writable. Git's safe-directory exception is
# scoped to this exact read-only checkout; it is needed because the disposable
# container's uid can differ from the checkout owner on CI or rootless hosts.
COMMON_ARGS="$DAEMON_ARGS $GIT_METADATA_ARGS -v $ROOT:$ROOT:ro -w $ROOT -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=$ROOT"

if [ "${1:-}" = "build" ]; then
  # shellcheck disable=SC2086
  exec docker run --rm $COMMON_ARGS \
    -v "$WORK_ROOT:$WORK_ROOT" \
    "$BOOTSTRAP_IMAGE" \
    "$@" \
    --work-root "$WORK_ROOT" \
    --output "$WORK_ROOT/environment-image-build.json"
fi

# shellcheck disable=SC2086
exec docker run --rm $COMMON_ARGS \
  "$BOOTSTRAP_IMAGE" \
  "$@"
