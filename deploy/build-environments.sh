#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PATH_HELPERS="$ROOT/deploy/noetrium-paths.sh"
. "$PATH_HELPERS"
BOOTSTRAP_IMAGE="${NOETRIUM_BOOTSTRAP_IMAGE:-noetrium/environment-builder:local}"
DOCKER_CLI_IMAGE="${NOETRIUM_DOCKER_CLI_IMAGE:-docker:27-cli}"
PYTHON_RUNTIME_IMAGE="${NOETRIUM_BOOTSTRAP_PYTHON_IMAGE:-python:3.12-slim-bookworm}"
MACHINE_STATE_ROOT="$(noetrium_machine_state_root "$ROOT")"
WORK_ROOT="${NOETRIUM_BUILD_WORK_ROOT:-$MACHINE_STATE_ROOT/environment-images}"
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

bootstrap_container_absent_once() {
  id="$1"
  if inspect_output="$(docker inspect "$id" 2>&1)"; then
    return 1
  fi
  case "$inspect_output" in
    *"No such object"*|*"No such container"*)
      return 0
      ;;
  esac
  if ! remaining="$(docker ps -aq --no-trunc --filter "id=$id" 2>/dev/null)"; then
    return 2
  fi
  [ -z "$remaining" ] && return 0
  return 1
}

bootstrap_container_absent() {
  id="$1"
  attempt=1
  last_status=2
  while [ "$attempt" -le 5 ]; do
    if bootstrap_container_absent_once "$id"; then
      return 0
    else
      last_status=$?
    fi
    [ "$attempt" -eq 5 ] && break
    sleep 0.05
    attempt=$((attempt + 1))
  done
  if [ "$last_status" -eq 2 ]; then
    echo "Unable to prove bootstrap container absence: $id" >&2
  fi
  return "$last_status"
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
    --tmpfs /tmp:rw,exec,nosuid,nodev,mode=1777 \
    --name "$BOOTSTRAP_CONTAINER_NAME" \
    --label "$BOOTSTRAP_MANAGED_LABEL=$BOOTSTRAP_MANAGED_VALUE" \
    --label "$OWNER_PID_LABEL=$$" \
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

docker_image_id() {
  image="$1"
  value="$(docker image inspect "$image" --format '{{.Id}}')" || return 1
  case "$value" in
    sha256:????????????????????????????????????????????????????????????????)
      digest="${value#sha256:}"
      case "$digest" in
        *[!0-9a-f]*)
          echo "Docker image identity is not lowercase SHA-256: $image -> $value" >&2
          return 1
          ;;
      esac
      ;;
    *)
      echo "Docker image identity is not immutable SHA-256: $image -> $value" >&2
      return 1
      ;;
  esac
  printf '%s\n' "$value"
}

verify_project_runtime_image() {
  image="$1"
  expected_key="$2"
  expected_base="$3"
  metadata="$(docker image inspect --format '{{.Id}}|{{index .Config.Labels "io.noetrium.project-runtime-key"}}|{{index .Config.Labels "io.noetrium.project-runtime-base-image-id"}}' "$image")" || return 1
  old_ifs="$IFS"
  IFS='|'
  set -- $metadata
  IFS="$old_ifs"
  image_id="${1:-}"
  runtime_key="${2:-}"
  base_image_id="${3:-}"
  case "$image_id" in
    sha256:????????????????????????????????????????????????????????????????) ;;
    *) return 1 ;;
  esac
  [ "$runtime_key" = "$expected_key" ] || return 1
  [ "$base_image_id" = "$expected_base" ] || return 1
}

command -v docker >/dev/null 2>&1 || {
  echo "Noetrium environment bootstrap requires Docker on the host." >&2
  exit 127
}

DOCKER_DAEMON_CAPABILITY_IDENTITY="${NOETRIUM_DOCKER_DAEMON_CAPABILITY_IDENTITY:-}"
if [ -z "$DOCKER_DAEMON_CAPABILITY_IDENTITY" ]; then
  DOCKER_DAEMON_CAPABILITY_IDENTITY="$(
    docker info --format '{{.ID}}|{{.ServerVersion}}|{{.Driver}}|{{.DefaultRuntime}}|{{json .Runtimes}}|{{json .CDISpecDirs}}' 2>/dev/null
  )" || {
    echo "Noetrium environment bootstrap cannot reach the active Docker daemon." >&2
    exit 1
  }
fi
[ -n "$DOCKER_DAEMON_CAPABILITY_IDENTITY" ] || {
  echo "Docker daemon did not publish a stable capability identity." >&2
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

DAEMON_SOCKET_GID=""
case "$DAEMON_HOST" in
  unix://*)
    DAEMON_SOCKET="${DAEMON_HOST#unix://}"
    test -S "$DAEMON_SOCKET" || {
      echo "Docker daemon socket is unavailable: $DAEMON_SOCKET" >&2
      exit 1
    }
    DAEMON_SOCKET_GID="$(stat -c '%g' "$DAEMON_SOCKET")"
    case "$DAEMON_SOCKET_GID" in
      ''|*[!0-9]*)
        echo "Docker daemon socket group identity is invalid: $DAEMON_SOCKET" >&2
        exit 1
        ;;
    esac
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

# One host-visible coordination namespace is shared by standalone environment
# builds and project-control runs. Durable content stays under WORK_ROOT; only
# ephemeral single-flight/liveness state belongs here.
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"
# Every bootstrap/control-plane Python process that can touch host-visible
# coordination or build state must use the invoking host identity. Running the
# generic builder as container root poisons 0600 single-flight locks and makes
# the next ordinary-user run unable to recover. Numeric identities work without
# an /etc/passwd entry; HOME stays on the private tmpfs.
BOOTSTRAP_IDENTITY_ARGS="--user $HOST_UID:$HOST_GID -e HOME=/tmp"
if [ -n "$DAEMON_SOCKET_GID" ]; then
  BOOTSTRAP_IDENTITY_ARGS="$BOOTSTRAP_IDENTITY_ARGS --group-add $DAEMON_SOCKET_GID"
fi
HOST_RUNTIME_BASE="${XDG_RUNTIME_DIR:-/run/user/$HOST_UID}"
if [ -d "$HOST_RUNTIME_BASE" ] && [ -w "$HOST_RUNTIME_BASE" ]; then
  CONTROL_COORDINATION_ROOT="$HOST_RUNTIME_BASE/noetrium"
elif [ -d /dev/shm ] && [ -w /dev/shm ]; then
  CONTROL_COORDINATION_ROOT="/dev/shm/noetrium-uid-$HOST_UID"
else
  echo "No writable host runtime coordination filesystem is available." >&2
  exit 1
fi
mkdir -p "$CONTROL_COORDINATION_ROOT"
chmod 0700 "$CONTROL_COORDINATION_ROOT"
test -w "$CONTROL_COORDINATION_ROOT" || {
  echo "Noetrium host runtime coordination root is not writable: $CONTROL_COORDINATION_ROOT" >&2
  exit 1
}
mkdir -p "$CONTROL_COORDINATION_ROOT/environment-build-locks" "$CONTROL_COORDINATION_ROOT/control-worker-locks"
chmod 0700 "$CONTROL_COORDINATION_ROOT/environment-build-locks" "$CONTROL_COORDINATION_ROOT/control-worker-locks"

mkdir -p "$WORK_ROOT"
WORK_ROOT="$(CDPATH= cd -- "$WORK_ROOT" && pwd)"

# Product bootstrap is a stable dependency/tooling capsule. Current Noetrium
# source is never baked into it: source is mounted read-only at execution time.
# Rebuild only when the bootstrap recipe, dependency declaration or concrete
# parent image identities change.
# Independent missing bootstrap parents are acquired concurrently on the
# first cold start. Keep all child pulls joined and re-verify immutable image
# identities before deriving the bootstrap build key. Warm starts do no pulls.
DOCKER_CLI_IMAGE_ID="$(docker_image_id "$DOCKER_CLI_IMAGE" 2>/dev/null || true)"
PYTHON_RUNTIME_IMAGE_ID="$(docker_image_id "$PYTHON_RUNTIME_IMAGE" 2>/dev/null || true)"
DOCKER_CLI_PULL_PID=""
PYTHON_RUNTIME_PULL_PID=""
if [ -z "$DOCKER_CLI_IMAGE_ID" ]; then
  docker pull "$DOCKER_CLI_IMAGE" &
  DOCKER_CLI_PULL_PID=$!
fi
if [ -z "$PYTHON_RUNTIME_IMAGE_ID" ]; then
  docker pull "$PYTHON_RUNTIME_IMAGE" &
  PYTHON_RUNTIME_PULL_PID=$!
fi
BOOTSTRAP_PARENT_PULL_FAILED=0
if [ -n "$DOCKER_CLI_PULL_PID" ]; then
  if ! wait "$DOCKER_CLI_PULL_PID"; then
    echo "Docker CLI bootstrap parent pull failed: $DOCKER_CLI_IMAGE" >&2
    BOOTSTRAP_PARENT_PULL_FAILED=1
  fi
fi
if [ -n "$PYTHON_RUNTIME_PULL_PID" ]; then
  if ! wait "$PYTHON_RUNTIME_PULL_PID"; then
    echo "Python bootstrap parent pull failed: $PYTHON_RUNTIME_IMAGE" >&2
    BOOTSTRAP_PARENT_PULL_FAILED=1
  fi
fi
[ "$BOOTSTRAP_PARENT_PULL_FAILED" -eq 0 ] || exit 1
if [ -z "$DOCKER_CLI_IMAGE_ID" ]; then
  DOCKER_CLI_IMAGE_ID="$(docker_image_id "$DOCKER_CLI_IMAGE")"
fi
if [ -z "$PYTHON_RUNTIME_IMAGE_ID" ]; then
  PYTHON_RUNTIME_IMAGE_ID="$(docker_image_id "$PYTHON_RUNTIME_IMAGE")"
fi
BOOTSTRAP_INPUT_DIGEST="$(
  {
    (CDPATH= cd -- "$ROOT" && sha256sum deploy/bootstrap/Dockerfile pyproject.toml)
    printf '%s\n' "$DOCKER_CLI_IMAGE_ID" "$PYTHON_RUNTIME_IMAGE_ID"
  } | sha256sum | awk '{print $1}'
)"
BOOTSTRAP_CACHED_DIGEST="$(
  docker image inspect "$BOOTSTRAP_IMAGE" \
    --format '{{index .Config.Labels "io.noetrium.bootstrap.input-sha256"}}' \
    2>/dev/null || true
)"
if [ "$BOOTSTRAP_CACHED_DIGEST" != "$BOOTSTRAP_INPUT_DIGEST" ]; then
  BOOTSTRAP_CONTEXT="$WORK_ROOT/bootstrap-context/$BOOTSTRAP_INPUT_DIGEST"
  mkdir -p "$BOOTSTRAP_CONTEXT"
  cp "$ROOT/deploy/bootstrap/Dockerfile" "$BOOTSTRAP_CONTEXT/Dockerfile"
  cp "$ROOT/pyproject.toml" "$BOOTSTRAP_CONTEXT/pyproject.toml"
  docker build \
    --build-arg "DOCKER_CLI_IMAGE=$DOCKER_CLI_IMAGE" \
    --build-arg "PYTHON_RUNTIME_IMAGE=$PYTHON_RUNTIME_IMAGE" \
    --build-arg "NOETRIUM_BOOTSTRAP_INPUT_DIGEST=$BOOTSTRAP_INPUT_DIGEST" \
    --tag "$BOOTSTRAP_IMAGE" \
    "$BOOTSTRAP_CONTEXT"
fi

# The bootstrap talks to the host Docker daemon. Preserve host absolute paths
# inside the control-plane container so daemon-side build contexts and Compose
# bind mounts resolve to the same files. Source stays read-only; only the
# dedicated build/runtime root is writable.
COMMON_ARGS="$DAEMON_ARGS $BOOTSTRAP_IDENTITY_ARGS -v $ROOT:$ROOT:ro -v $CONTROL_COORDINATION_ROOT:$CONTROL_COORDINATION_ROOT -w $ROOT -e PYTHONPATH=$ROOT -e PYTHONDONTWRITEBYTECODE=1 -e NOETRIUM_RUNTIME_COORDINATION_ROOT=$CONTROL_COORDINATION_ROOT -e NOETRIUM_DOCKER_CAPABILITY_VERIFIED=${NOETRIUM_DOCKER_CAPABILITY_VERIFIED:-0} -e BUILDX_GIT_INFO=false -e BUILDX_GIT_LABELS=false -e BUILDX_GIT_CHECK_DIRTY=false -e NOETRIUM_BOOTSTRAP_OWNER_PID=$$ -e NOETRIUM_BOOTSTRAP_OWNER_BOOT=$BOOT_ID -e NOETRIUM_BOOTSTRAP_OWNER_START=$OWNER_START"

DEPLOYMENT_ENV_FILE="${NOETRIUM_DEPLOYMENT_ENV_FILE:-}"
if [ -z "$DEPLOYMENT_ENV_FILE" ] && [ -f "$ROOT/deploy/.env" ]; then
  DEPLOYMENT_ENV_FILE="$ROOT/deploy/.env"
fi
if [ -n "$DEPLOYMENT_ENV_FILE" ]; then
  test -f "$DEPLOYMENT_ENV_FILE" || {
    echo "Noetrium deployment env file does not exist: $DEPLOYMENT_ENV_FILE" >&2
    exit 1
  }
  test ! -L "$DEPLOYMENT_ENV_FILE" || {
    echo "Noetrium deployment env file must not be a symlink: $DEPLOYMENT_ENV_FILE" >&2
    exit 1
  }
  DEPLOYMENT_ENV_FILE="$(CDPATH= cd -- "$(dirname "$DEPLOYMENT_ENV_FILE")" && pwd -P)/$(basename "$DEPLOYMENT_ENV_FILE")"
fi

if [ "${1:-}" = "control" ]; then
  shift
  [ "$#" -gt 0 ] || {
    echo "Noetrium control requires a Python entrypoint." >&2
    exit 2
  }
  CONTROL_STATE_ROOT="${NOETRIUM_CONTROL_STATE_ROOT:-$WORK_ROOT/control}"
  mkdir -p "$CONTROL_STATE_ROOT"
  CONTROL_STATE_ROOT="$(CDPATH= cd -- "$CONTROL_STATE_ROOT" && pwd)"
  CONTROL_RUNTIME_FABRIC_ROOT="${NOETRIUM_RUNTIME_FABRIC_ROOT:-$MACHINE_STATE_ROOT/runtime-fabric}"
  case "$CONTROL_RUNTIME_FABRIC_ROOT" in
    /*) ;;
    *)
      echo "NOETRIUM_RUNTIME_FABRIC_ROOT must be an absolute path." >&2
      exit 2
      ;;
  esac
  mkdir -p "$CONTROL_RUNTIME_FABRIC_ROOT"
  CONTROL_RUNTIME_FABRIC_ROOT="$(CDPATH= cd -- "$CONTROL_RUNTIME_FABRIC_ROOT" && pwd -P)"
  # The execution entrypoint persists the one authoritative Research graph
  # at root-set/research. Lifecycle actions must bind exactly that store;
  # a second research-os root silently loses the active cut and cannot cancel.
  PROJECT_RESEARCH_STATE_ROOT="$CONTROL_STATE_ROOT/research"
  mkdir -p "$PROJECT_RESEARCH_STATE_ROOT"
  CONTROL_ENV_FILE="${NOETRIUM_CONTROL_ENV_FILE:-$DEPLOYMENT_ENV_FILE}"

  CONTROL_PROJECT_ROOTS_FILE="${NOETRIUM_CONTROL_PROJECT_ROOTS_FILE:-}"
  CONTROL_HOST_RUNTIME="${NOETRIUM_CONTROL_HOST_RUNTIME:-0}"
  CONTROL_RUNTIME_ARGS=""
  CONTROL_IMAGE="$BOOTSTRAP_IMAGE"
  if [ "$CONTROL_HOST_RUNTIME" = "1" ]; then
    [ -n "$CONTROL_PROJECT_ROOTS_FILE" ] || {
      echo "Host-runtime control requires NOETRIUM_CONTROL_PROJECT_ROOTS_FILE." >&2
      exit 2
    }
    test -f "$CONTROL_PROJECT_ROOTS_FILE" && test ! -L "$CONTROL_PROJECT_ROOTS_FILE" || {
      echo "Control project root-set file must be a real regular file: $CONTROL_PROJECT_ROOTS_FILE" >&2
      exit 1
    }
    CANONICAL_ROOTS_TMP="$CONTROL_STATE_ROOT/project-roots.$$.tmp"
    : > "$CANONICAL_ROOTS_TMP"
    while IFS= read -r CONTROL_PROJECT_ROOT || [ -n "$CONTROL_PROJECT_ROOT" ]; do
      [ -n "$CONTROL_PROJECT_ROOT" ] || continue
      test -d "$CONTROL_PROJECT_ROOT" || {
        echo "Control project root does not exist: $CONTROL_PROJECT_ROOT" >&2
        exit 1
      }
      test ! -L "$CONTROL_PROJECT_ROOT" || {
        echo "Control project root must not be a symlink: $CONTROL_PROJECT_ROOT" >&2
        exit 1
      }
      CONTROL_PROJECT_ROOT="$(CDPATH= cd -- "$CONTROL_PROJECT_ROOT" && pwd -P)"
      printf '%s\n' "$CONTROL_PROJECT_ROOT" >> "$CANONICAL_ROOTS_TMP"
    done < "$CONTROL_PROJECT_ROOTS_FILE"
    [ -s "$CANONICAL_ROOTS_TMP" ] || {
      echo "Control project root-set must contain at least one root." >&2
      exit 2
    }
    CANONICAL_ROOTS_FILE="$CONTROL_STATE_ROOT/project-roots.canonical"
    sort -u "$CANONICAL_ROOTS_TMP" > "$CANONICAL_ROOTS_FILE"
    rm -f "$CANONICAL_ROOTS_TMP"
    CONTROL_PROJECT_ROOTS_FILE="$CANONICAL_ROOTS_FILE"
    CONTROL_PROJECT_ROOT_SET_DIGEST="$(sha256sum "$CONTROL_PROJECT_ROOTS_FILE" | awk '{print $1}')"
    CONTROL_HOME="$CONTROL_STATE_ROOT/home"
    mkdir -p "$CONTROL_HOME"

    CONTROL_IMAGE="$BOOTSTRAP_IMAGE"
    BOOTSTRAP_IMAGE_ID="$(docker_image_id "$BOOTSTRAP_IMAGE")"

    HOST_IDENTITY_ARGS=""
    HOST_IDENTITY_SOURCE=""
    if [ -s /etc/machine-id ]; then
      HOST_IDENTITY_SOURCE="/etc/machine-id"
      HOST_IDENTITY_ARGS="-v /etc/machine-id:/etc/machine-id:ro"
    elif [ -s /sys/class/dmi/id/product_uuid ]; then
      HOST_IDENTITY_SOURCE="/sys/class/dmi/id/product_uuid"
      HOST_IDENTITY_ARGS="-v /sys/class/dmi/id/product_uuid:/sys/class/dmi/id/product_uuid:ro"
    else
      echo "Noetrium controller attachment requires stable physical-host identity." >&2
      exit 1
    fi

    CONTROL_FABRIC_NAMESPACE_FILE="$CONTROL_STATE_ROOT/runtime-fabric.namespace"
    PROJECT_RUNTIME_INPUT_DIGEST="$(
      {
        while IFS= read -r CONTROL_PROJECT_ROOT || [ -n "$CONTROL_PROJECT_ROOT" ]; do
          sha256sum "$CONTROL_PROJECT_ROOT/pyproject.toml" | awk '{print $1}'
        done < "$CONTROL_PROJECT_ROOTS_FILE"
        sha256sum \
          "$ROOT/pyproject.toml" \
          "$ROOT/deploy/bootstrap/ProjectRuntime.Dockerfile" \
          "$ROOT/scripts/materialize_project_runtime.py" \
          "$ROOT/noetrium_platform/composition/runtime_coordination.py" \
          "$ROOT/noetrium_platform/foundation/kernel/kernel/lease_clock.py" \
          | awk '{print $1}'
        sha256sum "$HOST_IDENTITY_SOURCE" | awk '{print $1}'
        printf '%s\n' \
          "$CONTROL_PROJECT_ROOT_SET_DIGEST" \
          "$BOOTSTRAP_IMAGE_ID" \
          "$CONTROL_RUNTIME_FABRIC_ROOT" \
          "uid=$HOST_UID"
      } | sha256sum | awk '{print $1}'
    )"
    PROJECT_RUNTIME_RESULT_ROOT="$CONTROL_STATE_ROOT/project-runtime/materializer-results"
    PROJECT_RUNTIME_RESULT="$PROJECT_RUNTIME_RESULT_ROOT/$PROJECT_RUNTIME_INPUT_DIGEST.json"
    PROJECT_RUNTIME_KEY=""
    CONTROL_FABRIC_NAMESPACE_ROOT=""
    if [ -f "$PROJECT_RUNTIME_RESULT" ] && [ ! -L "$PROJECT_RUNTIME_RESULT" ] \
      && grep -Fq "\"materialization_input_digest\":\"$PROJECT_RUNTIME_INPUT_DIGEST\"" "$PROJECT_RUNTIME_RESULT" \
      && grep -Fq "\"base_image_id\":\"$BOOTSTRAP_IMAGE_ID\"" "$PROJECT_RUNTIME_RESULT"; then
      PROJECT_RUNTIME_KEY="$(
        sed -n 's/.*"runtime_key":"\([^"]*\)".*/\1/p' "$PROJECT_RUNTIME_RESULT"
      )"
      CONTROL_FABRIC_NAMESPACE_ROOT="$(
        sed -n 's/.*"fabric_namespace_root":"\([^"]*\)".*/\1/p' "$PROJECT_RUNTIME_RESULT"
      )"
    fi
    if [ -z "$PROJECT_RUNTIME_KEY" ]; then
      mkdir -p "$PROJECT_RUNTIME_RESULT_ROOT"
      PROJECT_RUNTIME_KEY="$(
        (
          set -- docker run --rm --init --restart no \
            --tmpfs /tmp:rw,exec,nosuid,nodev,mode=1777 \
            --user "$HOST_UID:$HOST_GID" \
            --entrypoint python3 \
            -e HOME=/tmp \
            -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
            -e PIP_NO_CACHE_DIR=1 \
            -e PYTHONPATH="$ROOT" \
            -e NOETRIUM_RUNTIME_FABRIC_ROOT="$CONTROL_RUNTIME_FABRIC_ROOT"
          if [ -n "$HOST_IDENTITY_SOURCE" ]; then
            set -- "$@" -v "$HOST_IDENTITY_SOURCE:$HOST_IDENTITY_SOURCE:ro"
          fi
          set -- "$@" -v "$ROOT:$ROOT:ro"
          while IFS= read -r CONTROL_PROJECT_ROOT || [ -n "$CONTROL_PROJECT_ROOT" ]; do
            set -- "$@" -v "$CONTROL_PROJECT_ROOT:$CONTROL_PROJECT_ROOT:ro"
          done < "$CONTROL_PROJECT_ROOTS_FILE"
          set -- "$@" \
            -v "$CONTROL_STATE_ROOT:$CONTROL_STATE_ROOT" \
            "$BOOTSTRAP_IMAGE" \
            "$ROOT/scripts/materialize_project_runtime.py"
          while IFS= read -r CONTROL_PROJECT_ROOT || [ -n "$CONTROL_PROJECT_ROOT" ]; do
            set -- "$@" --project-root "$CONTROL_PROJECT_ROOT"
          done < "$CONTROL_PROJECT_ROOTS_FILE"
          set -- "$@" \
            --platform-root "$ROOT" \
            --state-root "$CONTROL_STATE_ROOT" \
            --base-image-id "$BOOTSTRAP_IMAGE_ID" \
            --runtime-fabric-root-output "$CONTROL_FABRIC_NAMESPACE_FILE" \
            --result-output "$PROJECT_RUNTIME_RESULT" \
            --materialization-input-digest "$PROJECT_RUNTIME_INPUT_DIGEST"
          "$@"
        )
      )"
    fi
    test -f "$CONTROL_FABRIC_NAMESPACE_FILE" && test ! -L "$CONTROL_FABRIC_NAMESPACE_FILE" || {
      echo "Project runtime materializer did not publish Runtime Fabric namespace." >&2
      exit 1
    }
    MATERIALIZED_FABRIC_NAMESPACE_ROOT="$(cat "$CONTROL_FABRIC_NAMESPACE_FILE")"
    if [ -z "$CONTROL_FABRIC_NAMESPACE_ROOT" ]; then
      CONTROL_FABRIC_NAMESPACE_ROOT="$MATERIALIZED_FABRIC_NAMESPACE_ROOT"
    fi
    # The keyed materialization receipt is authoritative for this input digest.
    # The namespace sidecar is a mutable convenience cache and may describe a
    # prior worktree/fabric root. Validate the receipt, then converge the sidecar
    # atomically instead of rejecting a valid first run.
    case "$CONTROL_FABRIC_NAMESPACE_ROOT" in
      "$CONTROL_RUNTIME_FABRIC_ROOT"/*) ;;
      *)
        echo "Resolved Runtime Fabric namespace escaped configured root: $CONTROL_FABRIC_NAMESPACE_ROOT" >&2
        exit 2
        ;;
    esac
    test ! -L "$CONTROL_FABRIC_NAMESPACE_FILE" || {
      echo "Runtime Fabric namespace sidecar must not be a symlink." >&2
      exit 1
    }
    if [ "$CONTROL_FABRIC_NAMESPACE_ROOT" != "$MATERIALIZED_FABRIC_NAMESPACE_ROOT" ]; then
      CONTROL_FABRIC_NAMESPACE_TMP="$CONTROL_FABRIC_NAMESPACE_FILE.tmp.$$"
      ( umask 077; printf '%s\n' "$CONTROL_FABRIC_NAMESPACE_ROOT" > "$CONTROL_FABRIC_NAMESPACE_TMP" )
      mv -f "$CONTROL_FABRIC_NAMESPACE_TMP" "$CONTROL_FABRIC_NAMESPACE_FILE"
      MATERIALIZED_FABRIC_NAMESPACE_ROOT="$CONTROL_FABRIC_NAMESPACE_ROOT"
    fi
    case "$CONTROL_FABRIC_NAMESPACE_ROOT" in
      "$CONTROL_RUNTIME_FABRIC_ROOT"/*) ;;
      *)
        echo "Resolved Runtime Fabric namespace escaped configured root: $CONTROL_FABRIC_NAMESPACE_ROOT" >&2
        exit 2
        ;;
    esac
    if [ "$PROJECT_RUNTIME_KEY" != "base" ]; then
      [ "${#PROJECT_RUNTIME_KEY}" -eq 64 ] || {
        echo "Project runtime materializer returned invalid identity: $PROJECT_RUNTIME_KEY" >&2
        exit 1
      }
      case "$PROJECT_RUNTIME_KEY" in
        *[!0-9a-f]*)
          echo "Project runtime materializer returned non-SHA256 identity: $PROJECT_RUNTIME_KEY" >&2
          exit 1
          ;;
      esac
      PROJECT_RUNTIME_CONTEXT="$CONTROL_STATE_ROOT/project-runtime/objects/$PROJECT_RUNTIME_KEY"
      test -f "$PROJECT_RUNTIME_CONTEXT/Dockerfile" || {
        echo "Project runtime build context is incomplete: $PROJECT_RUNTIME_CONTEXT" >&2
        exit 1
      }
      PROJECT_BASE_ALIAS="noetrium/project-runtime-base:${BOOTSTRAP_IMAGE_ID#sha256:}"
      docker tag "$BOOTSTRAP_IMAGE_ID" "$PROJECT_BASE_ALIAS"
      [ "$(docker_image_id "$PROJECT_BASE_ALIAS")" = "$BOOTSTRAP_IMAGE_ID" ] || {
        echo "Project runtime base alias drifted from immutable bootstrap image." >&2
        exit 1
      }
      CONTROL_IMAGE="noetrium/project-runtime:$PROJECT_RUNTIME_KEY"
      if docker image inspect "$CONTROL_IMAGE" >/dev/null 2>&1; then
        verify_project_runtime_image           "$CONTROL_IMAGE" "$PROJECT_RUNTIME_KEY" "$BOOTSTRAP_IMAGE_ID" || {
          echo "Cached project runtime image identity/provenance drifted: $CONTROL_IMAGE" >&2
          exit 1
        }
      else
        docker build           --build-arg "BASE_IMAGE=$PROJECT_BASE_ALIAS"           --build-arg "NOETRIUM_PROJECT_RUNTIME_KEY=$PROJECT_RUNTIME_KEY"           --build-arg "NOETRIUM_PROJECT_RUNTIME_BASE_IMAGE_ID=$BOOTSTRAP_IMAGE_ID"           --tag "$CONTROL_IMAGE"           "$PROJECT_RUNTIME_CONTEXT"
        verify_project_runtime_image           "$CONTROL_IMAGE" "$PROJECT_RUNTIME_KEY" "$BOOTSTRAP_IMAGE_ID" || {
          echo "Built project runtime image failed provenance verification: $CONTROL_IMAGE" >&2
          exit 1
        }
      fi
    fi
    CONTROL_IMAGE_ID="$(docker_image_id "$CONTROL_IMAGE")"

    CONTROL_RUNTIME_ARGS="--network host $HOST_IDENTITY_ARGS -v $CONTROL_HOME:$CONTROL_HOME -w $ROOT -e HOME=$CONTROL_HOME -e PYTHONPATH=$ROOT -e NOETRIUM_PROJECT_STATE_ROOT=$PROJECT_RESEARCH_STATE_ROOT -e NOETRIUM_CONTROL_IMAGE_ID=$CONTROL_IMAGE_ID -e NOETRIUM_PROJECT_RUNTIME_KEY=$PROJECT_RUNTIME_KEY"
    while IFS= read -r CONTROL_PROJECT_ROOT || [ -n "$CONTROL_PROJECT_ROOT" ]; do
      CONTROL_RUNTIME_ARGS="$CONTROL_RUNTIME_ARGS -v $CONTROL_PROJECT_ROOT:$CONTROL_PROJECT_ROOT:ro"
    done < "$CONTROL_PROJECT_ROOTS_FILE"
    CONTROL_GPU_MODE="none"
    if command -v nvidia-smi >/dev/null 2>&1; then
      NVIDIA_HOST_TOPOLOGY="$(nvidia-smi -L 2>/dev/null || true)"
      if [ -n "$NVIDIA_HOST_TOPOLOGY" ]; then
        GPU_CAPABILITY_ROOT="$CONTROL_COORDINATION_ROOT/gpu-capability"
        mkdir -p "$GPU_CAPABILITY_ROOT"
        chmod 0700 "$GPU_CAPABILITY_ROOT"
        GPU_CAPABILITY_DIGEST="$(
          {
            printf '%s\n' "$DOCKER_DAEMON_CAPABILITY_IDENTITY"
            printf '%s\n' "$BOOT_ID"
            printf '%s\n' "$CONTROL_IMAGE_ID"
            printf '%s\n' "$NVIDIA_HOST_TOPOLOGY"
            for capability_path in \
              /etc/docker/daemon.json \
              /etc/nvidia-container-runtime/config.toml \
              /etc/cdi/nvidia.yaml \
              /var/run/cdi/nvidia.yaml
            do
              if [ -f "$capability_path" ] && [ ! -L "$capability_path" ]; then
                sha256sum "$capability_path"
              fi
            done
          } | sha256sum | awk '{print $1}'
        )"
        GPU_CAPABILITY_PASS="$GPU_CAPABILITY_ROOT/$GPU_CAPABILITY_DIGEST.pass"
        GPU_CAPABILITY_FAIL="$GPU_CAPABILITY_ROOT/$GPU_CAPABILITY_DIGEST.fail"
        if [ -f "$GPU_CAPABILITY_PASS" ] && [ ! -L "$GPU_CAPABILITY_PASS" ]; then
          CONTROL_RUNTIME_ARGS="$CONTROL_RUNTIME_ARGS --gpus all"
          CONTROL_GPU_MODE="all"
        elif [ -f "$GPU_CAPABILITY_FAIL" ] && [ ! -L "$GPU_CAPABILITY_FAIL" ]; then
          :
        elif docker run --rm --init --restart no --gpus all \
          --entrypoint nvidia-smi "$CONTROL_IMAGE" -L >/dev/null 2>&1; then
          GPU_CAPABILITY_TMP="$GPU_CAPABILITY_PASS.tmp-$$"
          printf '%s\n' "$GPU_CAPABILITY_DIGEST" > "$GPU_CAPABILITY_TMP"
          mv -f "$GPU_CAPABILITY_TMP" "$GPU_CAPABILITY_PASS"
          rm -f "$GPU_CAPABILITY_FAIL"
          CONTROL_RUNTIME_ARGS="$CONTROL_RUNTIME_ARGS --gpus all"
          CONTROL_GPU_MODE="all"
        else
          GPU_CAPABILITY_TMP="$GPU_CAPABILITY_FAIL.tmp-$$"
          printf '%s\n' "$GPU_CAPABILITY_DIGEST" > "$GPU_CAPABILITY_TMP"
          mv -f "$GPU_CAPABILITY_TMP" "$GPU_CAPABILITY_FAIL"
          rm -f "$GPU_CAPABILITY_PASS"
        fi
      fi
    fi
  elif [ "$CONTROL_HOST_RUNTIME" != "0" ]; then
    echo "NOETRIUM_CONTROL_HOST_RUNTIME must be 0 or 1." >&2
    exit 2
  fi

  CONTROL_RUNTIME_FABRIC_ROOT="${NOETRIUM_RUNTIME_FABRIC_ROOT:-${CONTROL_RUNTIME_FABRIC_ROOT:-}}"
  if [ -n "$CONTROL_RUNTIME_FABRIC_ROOT" ]; then
    mkdir -p "$CONTROL_RUNTIME_FABRIC_ROOT"
    CONTROL_RUNTIME_FABRIC_ROOT="$(CDPATH= cd -- "$CONTROL_RUNTIME_FABRIC_ROOT" && pwd -P)"
    CONTROL_RUNTIME_ARGS="$CONTROL_RUNTIME_ARGS -v $CONTROL_RUNTIME_FABRIC_ROOT:$CONTROL_RUNTIME_FABRIC_ROOT -e NOETRIUM_RUNTIME_FABRIC_ROOT=$CONTROL_RUNTIME_FABRIC_ROOT"
  fi

  CONTROL_RUNTIME_CACHE_ROOT="${NOETRIUM_RUNTIME_CACHE_ROOT:-$MACHINE_STATE_ROOT/runtime-cache}"
  case "$CONTROL_RUNTIME_CACHE_ROOT" in
    /*) ;;
    *)
      echo "NOETRIUM_RUNTIME_CACHE_ROOT must be an absolute path." >&2
      exit 2
      ;;
  esac
  mkdir -p "$CONTROL_RUNTIME_CACHE_ROOT"
  CONTROL_RUNTIME_CACHE_ROOT="$(CDPATH= cd -- "$CONTROL_RUNTIME_CACHE_ROOT" && pwd -P)"
  CONTROL_RUNTIME_ARGS="$CONTROL_RUNTIME_ARGS -v $CONTROL_RUNTIME_CACHE_ROOT:$CONTROL_RUNTIME_CACHE_ROOT -e NOETRIUM_RUNTIME_CACHE_ROOT=$CONTROL_RUNTIME_CACHE_ROOT"

  CONTROL_HUGGINGFACE_CACHE_ROOT="${NOETRIUM_HUGGINGFACE_CACHE_ROOT:-}"
  if [ -n "$CONTROL_HUGGINGFACE_CACHE_ROOT" ]; then
    case "$CONTROL_HUGGINGFACE_CACHE_ROOT" in
      /*) ;;
      *)
        echo "NOETRIUM_HUGGINGFACE_CACHE_ROOT must be an absolute path." >&2
        exit 2
        ;;
    esac
    test -d "$CONTROL_HUGGINGFACE_CACHE_ROOT" && test ! -L "$CONTROL_HUGGINGFACE_CACHE_ROOT" || {
      echo "Noetrium Hugging Face cache root must be a real directory: $CONTROL_HUGGINGFACE_CACHE_ROOT" >&2
      exit 1
    }
    CONTROL_HUGGINGFACE_CACHE_ROOT="$(CDPATH= cd -- "$CONTROL_HUGGINGFACE_CACHE_ROOT" && pwd -P)"
    CONTROL_RUNTIME_ARGS="$CONTROL_RUNTIME_ARGS -v $CONTROL_HUGGINGFACE_CACHE_ROOT:$CONTROL_HUGGINGFACE_CACHE_ROOT:ro -e NOETRIUM_HUGGINGFACE_CACHE_ROOT=$CONTROL_HUGGINGFACE_CACHE_ROOT"
  fi

  if [ -n "$CONTROL_ENV_FILE" ]; then
    test -f "$CONTROL_ENV_FILE" || {
      echo "Noetrium control env file does not exist: $CONTROL_ENV_FILE" >&2
      exit 1
    }
  fi

  CONTROL_INPUT_ROOT="${NOETRIUM_CONTROL_INPUT_ROOT:-}"
  if [ -z "$CONTROL_INPUT_ROOT" ] && [ "$CONTROL_HOST_RUNTIME" = "1" ]; then
    CONTROL_ASSET_REGISTRY="$CONTROL_FABRIC_NAMESPACE_ROOT/content/state/model/assets"
    if [ -d "$CONTROL_ASSET_REGISTRY" ]; then
      # Reference-path discovery is a projection of the durable model-asset
      # registry, never a second authority.  Fingerprint both active metadata
      # and retirement tombstones so every semantic registry change invalidates
      # the projection.  The expensive containerized JSON parser only runs on a
      # cache miss; ordinary control-plane attachment is constant-time.
      CONTROL_ASSET_REGISTRY_DIGEST="$(
        {
          find "$CONTROL_ASSET_REGISTRY" -maxdepth 1 -type f -name '*.json' \
            -exec sha256sum {} + 2>/dev/null || true
          if [ -d "$CONTROL_ASSET_REGISTRY/_retiring" ]; then
            find "$CONTROL_ASSET_REGISTRY/_retiring" -maxdepth 1 -type f -name '*.json' \
              -exec sha256sum {} + 2>/dev/null || true
          fi
        } | LC_ALL=C sort | sha256sum | awk '{print $1}'
      )"
      CONTROL_INPUT_ROOT_CACHE="$CONTROL_FABRIC_NAMESPACE_ROOT/content/state/model/control-input-root.cache"
      CONTROL_INPUT_ROOT_CACHE_HIT=0
      if [ -f "$CONTROL_INPUT_ROOT_CACHE" ] && [ ! -L "$CONTROL_INPUT_ROOT_CACHE" ]; then
        CACHED_ASSET_REGISTRY_DIGEST="$(sed -n '1p' "$CONTROL_INPUT_ROOT_CACHE")"
        if [ "$CACHED_ASSET_REGISTRY_DIGEST" = "$CONTROL_ASSET_REGISTRY_DIGEST" ]; then
          CONTROL_INPUT_ROOT="$(sed -n '2p' "$CONTROL_INPUT_ROOT_CACHE")"
          CONTROL_INPUT_ROOT_CACHE_HIT=1
        fi
      fi
      if [ "$CONTROL_INPUT_ROOT_CACHE_HIT" = "0" ]; then
        CONTROL_INPUT_ROOT="$(
          docker run --rm \
            --entrypoint python3 \
            -v "$CONTROL_RUNTIME_FABRIC_ROOT:$CONTROL_RUNTIME_FABRIC_ROOT:ro" \
            "$BOOTSTRAP_IMAGE" \
            -c 'import json, os, pathlib, sys
root=pathlib.Path(sys.argv[1])
retiring=root/"_retiring"
refs=[]
for path in sorted(root.glob("*.json")):
    if (retiring/path.name).exists():
        continue
    try:
        row=json.loads(path.read_text("utf-8"))
    except Exception:
        continue
    if row.get("mode")!="reference":
        continue
    raw=row.get("path")
    if isinstance(raw,str) and os.path.isabs(raw):
        refs.append(raw)
if refs:
    common=os.path.commonpath(refs)
    if common and common != os.path.sep:
        print(common)
' "$CONTROL_ASSET_REGISTRY"
        )"
        case "$CONTROL_INPUT_ROOT" in
          *'
'*)
            echo "Model reference attachment root must be one canonical path." >&2
            exit 1
            ;;
        esac
        CONTROL_INPUT_ROOT_CACHE_TMP="$CONTROL_INPUT_ROOT_CACHE.tmp.$$"
        ( umask 077; printf '%s\n%s\n' \
            "$CONTROL_ASSET_REGISTRY_DIGEST" "$CONTROL_INPUT_ROOT" \
            > "$CONTROL_INPUT_ROOT_CACHE_TMP" )
        mv -f "$CONTROL_INPUT_ROOT_CACHE_TMP" "$CONTROL_INPUT_ROOT_CACHE"
      fi
    fi
  fi
  if [ -n "$CONTROL_INPUT_ROOT" ]; then
    test -d "$CONTROL_INPUT_ROOT" || {
      echo "Noetrium control input root does not exist: $CONTROL_INPUT_ROOT" >&2
      exit 1
    }
    test ! -L "$CONTROL_INPUT_ROOT" || {
      echo "Noetrium control input root must not be a symlink: $CONTROL_INPUT_ROOT" >&2
      exit 1
    }
    CONTROL_INPUT_ROOT="$(CDPATH= cd -- "$CONTROL_INPUT_ROOT" && pwd -P)"
  fi

  if [ "$CONTROL_HOST_RUNTIME" = "1" ]; then
    CONTROL_ENV_DIGEST="none"
    if [ -n "$CONTROL_ENV_FILE" ]; then
      CONTROL_ENV_DIGEST="$(sha256sum "$CONTROL_ENV_FILE" | awk '{print $1}')"
    fi
    CONTROL_HOST_IDENTITY_DIGEST="$(sha256sum "$HOST_IDENTITY_SOURCE" | awk '{print $1}')"
    # The path alone is not sufficient control-worker identity. A durable
    # project state root can be atomically retired and recreated at the same
    # pathname; existing Docker bind mounts still reference the old filesystem
    # object. Fence worker reuse by the host-visible state-root device/inode
    # identity so a recreated state root necessarily gets fresh bind mounts.
    CONTROL_STATE_ROOT_IDENTITY="$(stat -Lc '%d:%i' "$CONTROL_STATE_ROOT")"
    case "$CONTROL_STATE_ROOT_IDENTITY" in
      *:*) ;;
      *)
        echo "Could not resolve control state-root filesystem identity: $CONTROL_STATE_ROOT" >&2
        exit 1
        ;;
    esac
    CONTROL_WORKER_PROJECT_KEY="$(
      printf '%s\n' "$CONTROL_PROJECT_ROOT_SET_DIGEST" "$CONTROL_STATE_ROOT" "$CONTROL_RUNTIME_FABRIC_ROOT"         | sha256sum | awk '{print $1}'
    )"
    CONTROL_SOURCE_DIGEST="$(
      {
        find "$ROOT/noetrium_platform" "$ROOT/scripts" -type f \
          \( -name '*.py' -o -name '*.pyi' \) -print0
        printf '%s\0' "$ROOT/pyproject.toml"
      } | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}'
    )"
    [ -n "$CONTROL_SOURCE_DIGEST" ] || {
      echo "Could not derive Noetrium control source digest." >&2
      exit 1
    }
    CONTROL_ENVIRONMENT_BUILD_DIGEST="none"
    CONTROL_ENVIRONMENT_BUILD_RECEIPT="$WORK_ROOT/environment-image-build.json"
    if [ -f "$CONTROL_ENVIRONMENT_BUILD_RECEIPT" ]; then
      CONTROL_ENVIRONMENT_BUILD_DIGEST="$(
        sha256sum "$CONTROL_ENVIRONMENT_BUILD_RECEIPT" | awk '{print $1}'
      )"
    fi
    CONTROL_NOFILE_SOFT="$(awk '/Max open files/ { print $4; exit }' /proc/$$/limits 2>/dev/null || true)"
    CONTROL_NOFILE_HARD="$(awk '/Max open files/ { print $5; exit }' /proc/$$/limits 2>/dev/null || true)"
    case "$CONTROL_NOFILE_SOFT:$CONTROL_NOFILE_HARD" in
      *[!0-9:]*|:*|*:) CONTROL_WORKER_ULIMIT_ARGS="" ;;
      *) CONTROL_WORKER_ULIMIT_ARGS="--ulimit nofile=$CONTROL_NOFILE_SOFT:$CONTROL_NOFILE_HARD" ;;
    esac
    CONTROL_WORKER_GENERATION="$(
      {
        printf '%s\n'           "schema=noetrium.project-control-worker.v8"           "daemon=$DOCKER_DAEMON_CAPABILITY_IDENTITY"           "boot=$BOOT_ID"           "image=$CONTROL_IMAGE_ID"           "runtime=$PROJECT_RUNTIME_KEY"           "root_set=$CONTROL_PROJECT_ROOT_SET_DIGEST"           "state=$CONTROL_STATE_ROOT"           "state_identity=$CONTROL_STATE_ROOT_IDENTITY"           "fabric=$CONTROL_RUNTIME_FABRIC_ROOT"           "cache=$CONTROL_RUNTIME_CACHE_ROOT"           "hf_cache=$CONTROL_HUGGINGFACE_CACHE_ROOT"           "work=$WORK_ROOT"           "input=$CONTROL_INPUT_ROOT"           "env=$CONTROL_ENV_DIGEST"           "gpu=$CONTROL_GPU_MODE"           "uid=$HOST_UID"           "gid=$HOST_GID"           "host=$CONTROL_HOST_IDENTITY_DIGEST"           "daemon_host=$DAEMON_HOST"           "daemon_gid=$DAEMON_SOCKET_GID"           "coordination=$CONTROL_COORDINATION_ROOT"           "source=$CONTROL_SOURCE_DIGEST"           "environment_build=$CONTROL_ENVIRONMENT_BUILD_DIGEST"           "nofile=$CONTROL_NOFILE_SOFT:$CONTROL_NOFILE_HARD"           "platform=$ROOT"
      } | sha256sum | awk '{print $1}'
    )"
    CONTROL_WORKER_NAME="noetrium-control-$(printf '%s' "$CONTROL_WORKER_GENERATION" | cut -c1-24)"
    CONTROL_WORKER_LABEL="io.noetrium.control-worker"
    CONTROL_WORKER_VALUE="root-set-v3"
    CONTROL_WORKER_PROJECT_LABEL="io.noetrium.control-worker-project"
    CONTROL_WORKER_GENERATION_LABEL="io.noetrium.control-worker-generation"
    CONTROL_WORKER_USE_ROOT="$CONTROL_COORDINATION_ROOT/control-worker-use-locks"
    CONTROL_WORKER_GC_LOCK="$CONTROL_COORDINATION_ROOT/control-worker-gc.lock"
    mkdir -p "$CONTROL_WORKER_USE_ROOT"
    CONTROL_WORKER_USE_LOCK="$CONTROL_WORKER_USE_ROOT/$CONTROL_WORKER_GENERATION.lock"
    # Every invocation holds a shared generation use-lock from before worker
    # realization until its request exits.  Cache GC may retire a worker only
    # after it acquires the corresponding exclusive use-lock, so a newly
    # arriving request cannot race an idle-worker sweep.
    exec 7>"$CONTROL_WORKER_USE_LOCK"
    flock -s 7

    control_worker_cache_cleanup() {
      status=$?
      trap - EXIT HUP INT TERM
      flock -u 7 >/dev/null 2>&1 || true
      exec 7>&-

      # Resident workers are preload caches, never authority.  Keep exactly
      # the current generation plus every generation whose shared use-lock is
      # still held.  Everything else is safe to retire once Docker also proves
      # it has no in-flight exec.  No idle timeout or fixed cache cardinality is
      # needed: liveness itself is the eviction policy.
      exec 6>"$CONTROL_WORKER_GC_LOCK"
      flock -x 6
      cache_ids="$(docker ps -aq --no-trunc \
        --filter "label=$CONTROL_WORKER_LABEL" 2>/dev/null || true)"
      for cache_id in $cache_ids; do
        cache_name="$(docker inspect --format '{{.Name}}' "$cache_id" 2>/dev/null || true)"
        [ "$cache_name" = "/$CONTROL_WORKER_NAME" ] && continue
        cache_generation="$(docker inspect --format '{{index .Config.Labels "io.noetrium.control-worker-generation"}}' "$cache_id" 2>/dev/null || true)"
        [ -n "$cache_generation" ] || continue
        cache_use_lock="$CONTROL_WORKER_USE_ROOT/$cache_generation.lock"
        exec 5>"$cache_use_lock"
        if flock -n -x 5; then
          cache_exec_count="$(docker inspect --format '{{len .ExecIDs}}' "$cache_id" 2>/dev/null || printf '1')"
          case "$cache_exec_count" in
            ''|*[!0-9]*) cache_exec_count=1 ;;
          esac
          if [ "$cache_exec_count" -eq 0 ]; then
            if ! remove_bootstrap_container_exact "$cache_id"; then
              echo "Unable to retire idle resident control cache: $cache_id" >&2
            fi
          fi
          flock -u 5 >/dev/null 2>&1 || true
        fi
        exec 5>&-
      done
      flock -u 6 >/dev/null 2>&1 || true
      exec 6>&-
      exit "$status"
    }
    trap control_worker_cache_cleanup EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM

    retire_control_worker_if_unused() {
      candidate_id="$1"
      candidate_generation="$(docker inspect --format '{{index .Config.Labels "io.noetrium.control-worker-generation"}}' "$candidate_id" 2>/dev/null || true)"
      # Workers predating generation-labelled use-locks can only be active via
      # Docker exec.  Current workers must additionally prove their generation
      # use-lock is unheld.
      if [ -n "$candidate_generation" ]; then
        candidate_use_lock="$CONTROL_WORKER_USE_ROOT/$candidate_generation.lock"
        exec 5>"$candidate_use_lock"
        if ! flock -n -x 5; then
          exec 5>&-
          return 0
        fi
      fi
      candidate_exec_count="$(docker inspect --format '{{len .ExecIDs}}' "$candidate_id" 2>/dev/null || printf '1')"
      case "$candidate_exec_count" in
        ''|*[!0-9]*) candidate_exec_count=1 ;;
      esac
      if [ "$candidate_exec_count" -eq 0 ]; then
        remove_bootstrap_container_exact "$candidate_id"
      fi
      if [ -n "$candidate_generation" ]; then
        flock -u 5 >/dev/null 2>&1 || true
        exec 5>&-
      fi
    }

    CONTROL_WORKER_LOCK_FILE="$CONTROL_COORDINATION_ROOT/control-worker-locks/$CONTROL_WORKER_PROJECT_KEY.lock"
    exec 9>"$CONTROL_WORKER_LOCK_FILE"
    flock -x 9

    # A resident worker is cache, never authority. Retire workers from older
    # worker protocols once they have no in-flight docker exec requests.
    # This is global rather than project-key scoped so protocol upgrades cannot
    # leave an unbounded set of permanently restarting warm-cache containers.
    LEGACY_CONTROL_WORKERS="$(docker ps -aq --no-trunc       --filter "label=$CONTROL_WORKER_LABEL" 2>/dev/null || true)"
    for worker_id in $LEGACY_CONTROL_WORKERS; do
      worker_protocol="$(docker inspect --format '{{index .Config.Labels "io.noetrium.control-worker"}}' "$worker_id" 2>/dev/null || true)"
      [ "$worker_protocol" = "$CONTROL_WORKER_VALUE" ] && continue
      retire_control_worker_if_unused "$worker_id"
    done

    # Current-protocol workers are also globally reclaimable caches. Project-key
    # isolation controls bind-mount reuse, not cache lifetime; the host-global
    # generation use-lock is the authority for in-flight ownership.
    STALE_CONTROL_WORKERS="$(docker ps -aq --no-trunc       --filter "label=$CONTROL_WORKER_LABEL=$CONTROL_WORKER_VALUE" 2>/dev/null || true)"
    for worker_id in $STALE_CONTROL_WORKERS; do
      worker_generation="$(docker inspect --format '{{index .Config.Labels "io.noetrium.control-worker-generation"}}' "$worker_id" 2>/dev/null || true)"
      [ "$worker_generation" = "$CONTROL_WORKER_GENERATION" ] && continue
      retire_control_worker_if_unused "$worker_id"
    done

    CONTROL_WORKER_METADATA="$(docker inspect --format '{{index .Config.Labels "io.noetrium.control-worker-generation"}}|{{.State.Running}}|{{.Image}}' "$CONTROL_WORKER_NAME" 2>/dev/null || true)"
    if [ -z "$CONTROL_WORKER_METADATA" ]; then
      CONTROL_WORKER_EXTRA_ARGS="-v $WORK_ROOT:$WORK_ROOT -v $CONTROL_STATE_ROOT:$CONTROL_STATE_ROOT -v $CONTROL_RUNTIME_FABRIC_ROOT:$CONTROL_RUNTIME_FABRIC_ROOT -v $CONTROL_COORDINATION_ROOT:$CONTROL_COORDINATION_ROOT -e NOETRIUM_CONTROL_WORKER_USE_LOCK=$CONTROL_WORKER_USE_LOCK -e NOETRIUM_CONTROL_STATE_ROOT=$CONTROL_STATE_ROOT -e NOETRIUM_RUNTIME_FABRIC_ROOT=$CONTROL_RUNTIME_FABRIC_ROOT -e NOETRIUM_CONTROL_PROJECT_ROOTS_FILE=$CONTROL_PROJECT_ROOTS_FILE -e NOETRIUM_CONTROL_ROOT_SET_DIGEST=$CONTROL_PROJECT_ROOT_SET_DIGEST -e NOETRIUM_PROJECT_RUNTIME_INPUT_DIGEST=$PROJECT_RUNTIME_INPUT_DIGEST -e NOETRIUM_BOOTSTRAP_INPUT_DIGEST=$BOOTSTRAP_INPUT_DIGEST -e NOETRIUM_BOOTSTRAP_IMAGE_ID=$BOOTSTRAP_IMAGE_ID -e NOETRIUM_DOCKER_DAEMON_CAPABILITY_IDENTITY=$DOCKER_DAEMON_CAPABILITY_IDENTITY -e NOETRIUM_DOCKER_CLI_IMAGE=$DOCKER_CLI_IMAGE -e NOETRIUM_DOCKER_CLI_IMAGE_ID=$DOCKER_CLI_IMAGE_ID -e NOETRIUM_PYTHON_RUNTIME_IMAGE=$PYTHON_RUNTIME_IMAGE -e NOETRIUM_PYTHON_RUNTIME_IMAGE_ID=$PYTHON_RUNTIME_IMAGE_ID -e NOETRIUM_CONTROL_GPU_MODE=$CONTROL_GPU_MODE -e NOETRIUM_CONTROL_ENV_DIGEST=$CONTROL_ENV_DIGEST -e NOETRIUM_CONTROL_FABRIC_NAMESPACE_ROOT=$CONTROL_FABRIC_NAMESPACE_ROOT -e NOETRIUM_HOST_IDENTITY_SOURCE=$HOST_IDENTITY_SOURCE -e NOETRIUM_HOST_UID=$HOST_UID"
      if [ -n "$CONTROL_INPUT_ROOT" ]; then
        CONTROL_WORKER_EXTRA_ARGS="$CONTROL_WORKER_EXTRA_ARGS -v $CONTROL_INPUT_ROOT:$CONTROL_INPUT_ROOT:ro -e NOETRIUM_CONTROL_INPUT_ROOT=$CONTROL_INPUT_ROOT"
      fi
      CONTROL_WORKER_ENV_ARGS=""
      if [ -n "$CONTROL_ENV_FILE" ]; then
        CONTROL_WORKER_ENV_ARGS="--env-file $CONTROL_ENV_FILE"
        # The resident worker re-attests the exact env file digest on every
        # request. Mount the canonical file at the same absolute path so the
        # runtime freshness proof can read the same bytes Docker consumed.
        CONTROL_WORKER_EXTRA_ARGS="$CONTROL_WORKER_EXTRA_ARGS -v $CONTROL_ENV_FILE:$CONTROL_ENV_FILE:ro -e NOETRIUM_CONTROL_ENV_FILE=$CONTROL_ENV_FILE"
      fi
      # shellcheck disable=SC2086
      if ! docker run -d --init --restart unless-stopped         --tmpfs /tmp:rw,exec,nosuid,nodev,mode=1777         $CONTROL_WORKER_ULIMIT_ARGS         --name "$CONTROL_WORKER_NAME"         --label "$CONTROL_WORKER_LABEL=$CONTROL_WORKER_VALUE"         --label "$CONTROL_WORKER_PROJECT_LABEL=$CONTROL_WORKER_PROJECT_KEY"         --label "$CONTROL_WORKER_GENERATION_LABEL=$CONTROL_WORKER_GENERATION"         --label "io.noetrium.control-worker-env-digest=$CONTROL_ENV_DIGEST"         --entrypoint python3         $COMMON_ARGS $CONTROL_RUNTIME_ARGS $CONTROL_WORKER_ENV_ARGS $CONTROL_WORKER_EXTRA_ARGS         "$CONTROL_IMAGE" "$ROOT/scripts/control_worker.py" --socket /tmp/noetrium-control.sock serve >/dev/null; then
        docker inspect "$CONTROL_WORKER_NAME" >/dev/null 2>&1 || {
          echo "Failed to realize project control worker: $CONTROL_WORKER_NAME" >&2
          exit 1
        }
      fi
      CONTROL_WORKER_METADATA="$(docker inspect --format '{{index .Config.Labels "io.noetrium.control-worker-generation"}}|{{.State.Running}}|{{.Image}}' "$CONTROL_WORKER_NAME")"
    fi

    CONTROL_WORKER_ACTUAL_GENERATION="$(printf '%s' "$CONTROL_WORKER_METADATA" | cut -d'|' -f1)"
    CONTROL_WORKER_RUNNING="$(printf '%s' "$CONTROL_WORKER_METADATA" | cut -d'|' -f2)"
    CONTROL_WORKER_IMAGE="$(printf '%s' "$CONTROL_WORKER_METADATA" | cut -d'|' -f3)"
    [ "$CONTROL_WORKER_ACTUAL_GENERATION" = "$CONTROL_WORKER_GENERATION" ] || {
      echo "Project control worker generation drifted: $CONTROL_WORKER_NAME" >&2
      exit 1
    }
    [ "$CONTROL_WORKER_IMAGE" = "$CONTROL_IMAGE_ID" ] || {
      echo "Project control worker image drifted: $CONTROL_WORKER_NAME" >&2
      exit 1
    }
    if [ "$CONTROL_WORKER_RUNNING" != "true" ]; then
      docker start "$CONTROL_WORKER_NAME" >/dev/null
    fi

    CONTROL_WORKER_SOCKET=/tmp/noetrium-control.sock
    if ! timeout 120 docker exec "$CONTROL_WORKER_NAME"       python3 "$ROOT/scripts/control_worker.py"       --socket "$CONTROL_WORKER_SOCKET" probe >/dev/null; then
      echo "Project control worker resident Python preload did not become ready: $CONTROL_WORKER_NAME" >&2
      exit 1
    fi
    CONTROL_WORKER_FAST_RECORD="$CONTROL_STATE_ROOT/control-worker.fast"
    CONTROL_WORKER_FAST_TMP="$CONTROL_WORKER_FAST_RECORD.tmp.$$"
    (
      umask 077
      printf '%s\n%s\n%s\n' "$CONTROL_WORKER_NAME" "$CONTROL_WORKER_GENERATION" "$CONTROL_IMAGE_ID" > "$CONTROL_WORKER_FAST_TMP"
    )
    mv -f "$CONTROL_WORKER_FAST_TMP" "$CONTROL_WORKER_FAST_RECORD"

    # Worker realization is single-flight, but requests are not held behind
    # this lock; a long research run must not block inspect/reconcile callers.
    flock -u 9
    exec 9>&-

    CONTROL_REQUEST_LEASE_DIR="$CONTROL_STATE_ROOT/control-request-leases"
    mkdir -p "$CONTROL_REQUEST_LEASE_DIR"
    CONTROL_REQUEST_LEASE="$CONTROL_REQUEST_LEASE_DIR/$BOOT_ID.$$.$OWNER_START.lock"
    CONTROL_REQUEST_CANCEL="$CONTROL_REQUEST_LEASE.cancel"
    rm -f "$CONTROL_REQUEST_CANCEL"
    exec 8>"$CONTROL_REQUEST_LEASE"
    flock -x 8
    CONTROL_REQUEST_LEASE_OPEN=1
    CONTROL_REQUEST_DOCKER_PID=""

    control_request_detach() {
      detach_status="$1"
      trap - HUP INT TERM
      # Transport lifetime is observational. HUP may detach an observer without
      # changing execution authority; explicit owner INT/TERM is handled by the
      # cancellation path below.
      if [ "${CONTROL_REQUEST_LEASE_OPEN:-0}" = "1" ]; then
        flock -u 8 >/dev/null 2>&1 || true
        exec 8>&-
        CONTROL_REQUEST_LEASE_OPEN=0
      fi
      rm -f "$CONTROL_REQUEST_LEASE"
      if [ -n "${CONTROL_REQUEST_DOCKER_PID:-}" ]; then
        kill -TERM "$CONTROL_REQUEST_DOCKER_PID" >/dev/null 2>&1 || true
      fi
      exit "$detach_status"
    }
    control_request_cancel() {
      cancel_status="$1"
      trap - HUP INT TERM
      # INT/TERM is an explicit stop of this owner generation. Publish the
      # request-scoped durable marker before detaching the observing docker-exec
      # client so the resident supervisor terminates exactly this execution.
      cancel_tmp="$CONTROL_REQUEST_CANCEL.tmp.$$"
      (
        umask 077
        printf '%s\n' "owner-signal=$cancel_status" > "$cancel_tmp"
      )
      mv -f "$cancel_tmp" "$CONTROL_REQUEST_CANCEL"
      control_request_detach "$cancel_status"
    }
    trap 'control_request_detach 129' HUP
    trap 'control_request_cancel 130' INT
    trap 'control_request_cancel 143' TERM

    # Run the client asynchronously so POSIX shells process cancellation traps
    # while waiting. A synchronous foreground docker exec defers TERM/INT until
    # the request exits, which would keep the owner lease live indefinitely.
    docker exec \
      -e NOETRIUM_BOOTSTRAP_OWNER_PID="$$" \
      -e NOETRIUM_BOOTSTRAP_OWNER_BOOT="$BOOT_ID" \
      -e NOETRIUM_BOOTSTRAP_OWNER_START="$OWNER_START" \
      -e NOETRIUM_CONTROL_REQUEST_LEASE="$CONTROL_REQUEST_LEASE" \
      "$CONTROL_WORKER_NAME" \
      python3 "$ROOT/scripts/control_worker.py" \
      --socket "$CONTROL_WORKER_SOCKET" request -- "$@" 8>&- &
    CONTROL_REQUEST_DOCKER_PID=$!
    if wait "$CONTROL_REQUEST_DOCKER_PID"; then
      CONTROL_REQUEST_STATUS=0
    else
      CONTROL_REQUEST_STATUS=$?
    fi
    CONTROL_REQUEST_DOCKER_PID=""
    CONTROL_REQUEST_CANCELLED=0
    if [ -e "$CONTROL_REQUEST_CANCEL" ]; then
      CONTROL_REQUEST_CANCELLED=1
    fi
    if [ "$CONTROL_REQUEST_LEASE_OPEN" = "1" ]; then
      flock -u 8
      exec 8>&-
      CONTROL_REQUEST_LEASE_OPEN=0
    fi
    rm -f "$CONTROL_REQUEST_LEASE" "$CONTROL_REQUEST_CANCEL"
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM
    # Explicit cancellation is terminal for this request generation.  Never
    # reinterpret it as resident-worker drift and resubmit the same research.
    if [ "$CONTROL_REQUEST_CANCELLED" -eq 1 ]; then
      exit 130
    fi
    if [ "$CONTROL_REQUEST_STATUS" -eq 0 ]; then
      exit 0
    else
      if [ "$CONTROL_REQUEST_STATUS" -eq 74 ] || [ "$CONTROL_REQUEST_STATUS" -eq 75 ]; then
        CONTROL_RESTART_COUNT="${NOETRIUM_CONTROL_RESIDENT_RESTART_COUNT:-0}"
        case "$CONTROL_RESTART_COUNT" in
          ''|*[!0-9]*) CONTROL_RESTART_COUNT=0 ;;
        esac
        if [ "$CONTROL_RESTART_COUNT" -lt 4 ]; then
          exec 9>"$CONTROL_WORKER_LOCK_FILE"
          flock -x 9
          worker_exec_count="$(docker inspect --format '{{len .ExecIDs}}' "$CONTROL_WORKER_NAME" 2>/dev/null || printf '0')"
          case "$worker_exec_count" in
            ''|*[!0-9]*) worker_exec_count=1 ;;
          esac
          if [ "$worker_exec_count" -eq 0 ]; then
            remove_bootstrap_container_exact "$CONTROL_WORKER_NAME"
          fi
          flock -u 9
          exec 9>&-
          CONTROL_RESTART_COUNT=$((CONTROL_RESTART_COUNT + 1))
          export NOETRIUM_CONTROL_RESIDENT_RESTART_COUNT="$CONTROL_RESTART_COUNT"
          exec "$0" control "$@"
        fi
        echo "Resident control worker did not reach an attested fixed point after $CONTROL_RESTART_COUNT restarts." >&2
      fi
      exit "$CONTROL_REQUEST_STATUS"
    fi
  fi

  if [ -n "$CONTROL_ENV_FILE" ]; then
    if [ -n "$CONTROL_INPUT_ROOT" ]; then
      # shellcheck disable=SC2086
      run_bootstrap_container --entrypoint python3 $COMMON_ARGS $CONTROL_RUNTIME_ARGS \
        --env-file "$CONTROL_ENV_FILE" \
        -v "$WORK_ROOT:$WORK_ROOT" \
        -v "$CONTROL_STATE_ROOT:$CONTROL_STATE_ROOT" \
        -v "$CONTROL_RUNTIME_FABRIC_ROOT:$CONTROL_RUNTIME_FABRIC_ROOT" \
        -v "$CONTROL_INPUT_ROOT:$CONTROL_INPUT_ROOT:ro" \
        -e NOETRIUM_CONTROL_STATE_ROOT="$CONTROL_STATE_ROOT" \
        -e NOETRIUM_RUNTIME_FABRIC_ROOT="$CONTROL_RUNTIME_FABRIC_ROOT" \
        -e NOETRIUM_CONTROL_INPUT_ROOT="$CONTROL_INPUT_ROOT" \
        "$CONTROL_IMAGE" "$@"
    else
      # shellcheck disable=SC2086
      run_bootstrap_container --entrypoint python3 $COMMON_ARGS $CONTROL_RUNTIME_ARGS \
        --env-file "$CONTROL_ENV_FILE" \
        -v "$WORK_ROOT:$WORK_ROOT" \
        -v "$CONTROL_STATE_ROOT:$CONTROL_STATE_ROOT" \
        -v "$CONTROL_RUNTIME_FABRIC_ROOT:$CONTROL_RUNTIME_FABRIC_ROOT" \
        -e NOETRIUM_CONTROL_STATE_ROOT="$CONTROL_STATE_ROOT" \
        -e NOETRIUM_RUNTIME_FABRIC_ROOT="$CONTROL_RUNTIME_FABRIC_ROOT" \
        "$CONTROL_IMAGE" "$@"
    fi
    exit $?
  fi

  if [ -n "$CONTROL_INPUT_ROOT" ]; then
    # shellcheck disable=SC2086
    run_bootstrap_container --entrypoint python3 $COMMON_ARGS $CONTROL_RUNTIME_ARGS \
      -v "$WORK_ROOT:$WORK_ROOT" \
      -v "$CONTROL_STATE_ROOT:$CONTROL_STATE_ROOT" \
        -v "$CONTROL_RUNTIME_FABRIC_ROOT:$CONTROL_RUNTIME_FABRIC_ROOT" \
      -v "$CONTROL_INPUT_ROOT:$CONTROL_INPUT_ROOT:ro" \
      -e NOETRIUM_CONTROL_STATE_ROOT="$CONTROL_STATE_ROOT" \
        -e NOETRIUM_RUNTIME_FABRIC_ROOT="$CONTROL_RUNTIME_FABRIC_ROOT" \
      -e NOETRIUM_CONTROL_INPUT_ROOT="$CONTROL_INPUT_ROOT" \
      "$CONTROL_IMAGE" "$@"
  else
    # shellcheck disable=SC2086
    run_bootstrap_container --entrypoint python3 $COMMON_ARGS $CONTROL_RUNTIME_ARGS \
      -v "$WORK_ROOT:$WORK_ROOT" \
      -v "$CONTROL_STATE_ROOT:$CONTROL_STATE_ROOT" \
        -v "$CONTROL_RUNTIME_FABRIC_ROOT:$CONTROL_RUNTIME_FABRIC_ROOT" \
      -e NOETRIUM_CONTROL_STATE_ROOT="$CONTROL_STATE_ROOT" \
        -e NOETRIUM_RUNTIME_FABRIC_ROOT="$CONTROL_RUNTIME_FABRIC_ROOT" \
      "$CONTROL_IMAGE" "$@"
  fi
  exit $?
fi

if [ "${1:-}" = "build" ]; then
  if [ -n "$DEPLOYMENT_ENV_FILE" ]; then
    # Build-time deployment input is mounted read-only and filtered inside the
    # builder against registry-declared build inputs. Never inject unrelated
    # deployment variables or secrets into the environment build container.
    # shellcheck disable=SC2086
    run_bootstrap_container $COMMON_ARGS \
      -v "$DEPLOYMENT_ENV_FILE:/run/noetrium/build-input.env:ro" \
      -v "$WORK_ROOT:$WORK_ROOT" \
      "$BOOTSTRAP_IMAGE" \
      "$@" \
      --work-root "$WORK_ROOT" \
      --output "$WORK_ROOT/environment-image-build.json" \
      --build-input-env-file /run/noetrium/build-input.env
  else
    # shellcheck disable=SC2086
    run_bootstrap_container $COMMON_ARGS \
      -v "$WORK_ROOT:$WORK_ROOT" \
      "$BOOTSTRAP_IMAGE" \
      "$@" \
      --work-root "$WORK_ROOT" \
      --output "$WORK_ROOT/environment-image-build.json"
  fi
  exit $?
fi

# shellcheck disable=SC2086
run_bootstrap_container $COMMON_ARGS \
  "$BOOTSTRAP_IMAGE" \
  "$@"
exit $?
