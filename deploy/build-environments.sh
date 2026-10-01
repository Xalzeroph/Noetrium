#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
BOOTSTRAP_IMAGE="${NOETRIUM_BOOTSTRAP_IMAGE:-noetrium/environment-builder:local}"
DOCKER_CLI_IMAGE="${NOETRIUM_DOCKER_CLI_IMAGE:-docker:27-cli}"
PYTHON_RUNTIME_IMAGE="${NOETRIUM_BOOTSTRAP_PYTHON_IMAGE:-python:3.12-slim-bookworm}"
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

DOCKER_DAEMON_CAPABILITY_IDENTITY="$(
  docker info --format '{{.ID}}|{{.ServerVersion}}|{{.Driver}}|{{.DefaultRuntime}}|{{json .Runtimes}}|{{json .CDISpecDirs}}' 2>/dev/null
)" || {
  echo "Noetrium environment bootstrap cannot reach the active Docker daemon." >&2
  exit 1
}
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
mkdir -p "$CONTROL_COORDINATION_ROOT/environment-build-locks"
chmod 0700 "$CONTROL_COORDINATION_ROOT/environment-build-locks"

mkdir -p "$WORK_ROOT"
WORK_ROOT="$(CDPATH= cd -- "$WORK_ROOT" && pwd)"

# Product bootstrap is a stable dependency/tooling capsule. Current Noetrium
# source is never baked into it: source is mounted read-only at execution time.
# Rebuild only when the bootstrap recipe, dependency declaration or concrete
# parent image identities change.
for bootstrap_parent in "$DOCKER_CLI_IMAGE" "$PYTHON_RUNTIME_IMAGE"; do
  docker image inspect "$bootstrap_parent" >/dev/null 2>&1 || docker pull "$bootstrap_parent"
done
DOCKER_CLI_IMAGE_ID="$(docker_image_id "$DOCKER_CLI_IMAGE")"
PYTHON_RUNTIME_IMAGE_ID="$(docker_image_id "$PYTHON_RUNTIME_IMAGE")"
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
COMMON_ARGS="$DAEMON_ARGS -v $ROOT:$ROOT:ro -v $CONTROL_COORDINATION_ROOT:$CONTROL_COORDINATION_ROOT -w $ROOT -e PYTHONPATH=$ROOT -e PYTHONDONTWRITEBYTECODE=1 -e NOETRIUM_RUNTIME_COORDINATION_ROOT=$CONTROL_COORDINATION_ROOT -e NOETRIUM_DOCKER_CAPABILITY_VERIFIED=${NOETRIUM_DOCKER_CAPABILITY_VERIFIED:-0} -e BUILDX_GIT_INFO=false -e BUILDX_GIT_LABELS=false -e BUILDX_GIT_CHECK_DIRTY=false -e NOETRIUM_BOOTSTRAP_OWNER_PID=$$ -e NOETRIUM_BOOTSTRAP_OWNER_BOOT=$BOOT_ID -e NOETRIUM_BOOTSTRAP_OWNER_START=$OWNER_START"

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
  CONTROL_RUNTIME_FABRIC_ROOT="${NOETRIUM_RUNTIME_FABRIC_ROOT:-$CONTROL_STATE_ROOT/runtime-fabric}"
  case "$CONTROL_RUNTIME_FABRIC_ROOT" in
    /*) ;;
    *)
      echo "NOETRIUM_RUNTIME_FABRIC_ROOT must be an absolute path." >&2
      exit 2
      ;;
  esac
  mkdir -p "$CONTROL_RUNTIME_FABRIC_ROOT"
  CONTROL_RUNTIME_FABRIC_ROOT="$(CDPATH= cd -- "$CONTROL_RUNTIME_FABRIC_ROOT" && pwd -P)"
  PROJECT_RESEARCH_STATE_ROOT="$CONTROL_STATE_ROOT/research-os"
  mkdir -p "$PROJECT_RESEARCH_STATE_ROOT"
  CONTROL_ENV_FILE="${NOETRIUM_CONTROL_ENV_FILE:-$DEPLOYMENT_ENV_FILE}"

  CONTROL_PROJECT_ROOT="${NOETRIUM_CONTROL_PROJECT_ROOT:-}"
  CONTROL_HOST_RUNTIME="${NOETRIUM_CONTROL_HOST_RUNTIME:-0}"
  CONTROL_RUNTIME_ARGS=""
  CONTROL_IMAGE="$BOOTSTRAP_IMAGE"
  if [ "$CONTROL_HOST_RUNTIME" = "1" ]; then
    [ -n "$CONTROL_PROJECT_ROOT" ] || {
      echo "Host-runtime control requires NOETRIUM_CONTROL_PROJECT_ROOT." >&2
      exit 2
    }
    test -d "$CONTROL_PROJECT_ROOT" || {
      echo "Control project root does not exist: $CONTROL_PROJECT_ROOT" >&2
      exit 1
    }
    test ! -L "$CONTROL_PROJECT_ROOT" || {
      echo "Control project root must not be a symlink: $CONTROL_PROJECT_ROOT" >&2
      exit 1
    }
    CONTROL_PROJECT_ROOT="$(CDPATH= cd -- "$CONTROL_PROJECT_ROOT" && pwd -P)"
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
        sha256sum \
          "$CONTROL_PROJECT_ROOT/pyproject.toml" \
          "$ROOT/pyproject.toml" \
          "$ROOT/deploy/bootstrap/ProjectRuntime.Dockerfile" \
          "$ROOT/scripts/materialize_project_runtime.py" \
          "$ROOT/noetrium_platform/composition/runtime_coordination.py" \
          "$ROOT/noetrium_platform/infrastructure/resources/lease/runtime/clock.py" \
          "$ROOT/noetrium_platform/foundation/kernel/kernel/lease_clock.py" \
          | awk '{print $1}'
        sha256sum "$HOST_IDENTITY_SOURCE" | awk '{print $1}'
        if [ -e "$CONTROL_PROJECT_ROOT/project.dependencies.lock.json" ]; then
          test -f "$CONTROL_PROJECT_ROOT/project.dependencies.lock.json" \
            && test ! -L "$CONTROL_PROJECT_ROOT/project.dependencies.lock.json" || {
              echo "Project dependency lock must be a real regular file." >&2
              exit 1
            }
          sha256sum "$CONTROL_PROJECT_ROOT/project.dependencies.lock.json" | awk '{print $1}'
        else
          printf '%s\n' 'project.dependencies.lock.json:absent'
        fi
        printf '%s\n' "$BOOTSTRAP_IMAGE_ID" "$CONTROL_RUNTIME_FABRIC_ROOT" "uid=$HOST_UID"
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
      # shellcheck disable=SC2086
      PROJECT_RUNTIME_KEY="$(
        docker run --rm --init --restart no           --tmpfs /tmp:rw,exec,nosuid,nodev,mode=1777           --user "$HOST_UID:$HOST_GID"           --entrypoint python3           -e HOME=/tmp           -e PIP_DISABLE_PIP_VERSION_CHECK=1           -e PIP_NO_CACHE_DIR=1           -e PYTHONPATH="$ROOT"           -e NOETRIUM_RUNTIME_FABRIC_ROOT="$CONTROL_RUNTIME_FABRIC_ROOT"           $HOST_IDENTITY_ARGS           -v "$ROOT:$ROOT:ro"           -v "$CONTROL_PROJECT_ROOT:$CONTROL_PROJECT_ROOT"           -v "$CONTROL_STATE_ROOT:$CONTROL_STATE_ROOT"           "$BOOTSTRAP_IMAGE"           "$ROOT/scripts/materialize_project_runtime.py"           --project-root "$CONTROL_PROJECT_ROOT"           --platform-root "$ROOT"           --state-root "$CONTROL_STATE_ROOT"           --base-image-id "$BOOTSTRAP_IMAGE_ID"           --runtime-fabric-root-output "$CONTROL_FABRIC_NAMESPACE_FILE"           --result-output "$PROJECT_RUNTIME_RESULT"           --materialization-input-digest "$PROJECT_RUNTIME_INPUT_DIGEST"
      )"
    fi
    test -f "$CONTROL_FABRIC_NAMESPACE_FILE" && test ! -L "$CONTROL_FABRIC_NAMESPACE_FILE" || {
      echo "Project runtime materializer did not publish Runtime Fabric namespace." >&2
      exit 1
    }
    MATERIALIZED_FABRIC_NAMESPACE_ROOT="$(cat "$CONTROL_FABRIC_NAMESPACE_FILE")"
    if [ -z "$CONTROL_FABRIC_NAMESPACE_ROOT" ]; then
      CONTROL_FABRIC_NAMESPACE_ROOT="$MATERIALIZED_FABRIC_NAMESPACE_ROOT"
    elif [ "$CONTROL_FABRIC_NAMESPACE_ROOT" != "$MATERIALIZED_FABRIC_NAMESPACE_ROOT" ]; then
      echo "Runtime Fabric namespace receipt/sidecar drifted." >&2
      exit 1
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

    CONTROL_RUNTIME_ARGS="--user $HOST_UID:$HOST_GID --network host $HOST_IDENTITY_ARGS -v $CONTROL_PROJECT_ROOT:$CONTROL_PROJECT_ROOT -v $CONTROL_HOME:$CONTROL_HOME -w $CONTROL_PROJECT_ROOT -e HOME=$CONTROL_HOME -e PYTHONPATH=$ROOT:$CONTROL_PROJECT_ROOT/src -e NOETRIUM_PROJECT_STATE_ROOT=$PROJECT_RESEARCH_STATE_ROOT -e NOETRIUM_CONTROL_IMAGE_ID=$CONTROL_IMAGE_ID -e NOETRIUM_PROJECT_RUNTIME_KEY=$PROJECT_RUNTIME_KEY"
    CONTROL_GPU_MODE="none"
    if [ -n "$DAEMON_SOCKET_GID" ]; then
      CONTROL_RUNTIME_ARGS="$CONTROL_RUNTIME_ARGS --group-add $DAEMON_SOCKET_GID"
    fi
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

  CONTROL_RUNTIME_FABRIC_ROOT="${NOETRIUM_RUNTIME_FABRIC_ROOT:-}"
  if [ -n "$CONTROL_RUNTIME_FABRIC_ROOT" ]; then
    mkdir -p "$CONTROL_RUNTIME_FABRIC_ROOT"
    CONTROL_RUNTIME_FABRIC_ROOT="$(CDPATH= cd -- "$CONTROL_RUNTIME_FABRIC_ROOT" && pwd -P)"
    CONTROL_RUNTIME_ARGS="$CONTROL_RUNTIME_ARGS -v $CONTROL_RUNTIME_FABRIC_ROOT:$CONTROL_RUNTIME_FABRIC_ROOT -e NOETRIUM_RUNTIME_FABRIC_ROOT=$CONTROL_RUNTIME_FABRIC_ROOT"
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
      CONTROL_INPUT_ROOT="$(
        docker run --rm           --entrypoint python3           -v "$CONTROL_PROJECT_ROOT:$CONTROL_PROJECT_ROOT:ro"           -v "$CONTROL_STATE_ROOT:$CONTROL_STATE_ROOT:ro"           -v "$CONTROL_RUNTIME_FABRIC_ROOT:$CONTROL_RUNTIME_FABRIC_ROOT:ro"           "$BOOTSTRAP_IMAGE"           -c 'import json, os, pathlib, sys
root=pathlib.Path(sys.argv[1])
refs=[]
for path in sorted(root.glob("*.json")):
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
    CONTROL_WORKER_PROJECT_KEY="$(
      printf '%s\n' "$CONTROL_PROJECT_ROOT" "$CONTROL_STATE_ROOT" "$CONTROL_RUNTIME_FABRIC_ROOT"         | sha256sum | awk '{print $1}'
    )"
    CONTROL_WORKER_GENERATION="$(
      {
        printf '%s\n'           "schema=noetrium.project-control-worker.v1"           "daemon=$DOCKER_DAEMON_CAPABILITY_IDENTITY"           "boot=$BOOT_ID"           "image=$CONTROL_IMAGE_ID"           "runtime=$PROJECT_RUNTIME_KEY"           "project=$CONTROL_PROJECT_ROOT"           "state=$CONTROL_STATE_ROOT"           "fabric=$CONTROL_RUNTIME_FABRIC_ROOT"           "input=$CONTROL_INPUT_ROOT"           "env=$CONTROL_ENV_DIGEST"           "gpu=$CONTROL_GPU_MODE"           "uid=$HOST_UID"           "gid=$HOST_GID"           "host=$CONTROL_HOST_IDENTITY_DIGEST"           "daemon_host=$DAEMON_HOST"           "daemon_gid=$DAEMON_SOCKET_GID"           "coordination=$CONTROL_COORDINATION_ROOT"           "platform=$ROOT"
      } | sha256sum | awk '{print $1}'
    )"
    CONTROL_WORKER_NAME="noetrium-control-$(printf '%s' "$CONTROL_WORKER_GENERATION" | cut -c1-24)"
    CONTROL_WORKER_LABEL="io.noetrium.control-worker"
    CONTROL_WORKER_VALUE="project-v1"
    CONTROL_WORKER_PROJECT_LABEL="io.noetrium.control-worker-project"
    CONTROL_WORKER_GENERATION_LABEL="io.noetrium.control-worker-generation"

    STALE_CONTROL_WORKERS="$(docker ps -aq --no-trunc       --filter "label=$CONTROL_WORKER_LABEL=$CONTROL_WORKER_VALUE"       --filter "label=$CONTROL_WORKER_PROJECT_LABEL=$CONTROL_WORKER_PROJECT_KEY" 2>/dev/null || true)"
    for worker_id in $STALE_CONTROL_WORKERS; do
      worker_generation="$(docker inspect --format '{{index .Config.Labels "io.noetrium.control-worker-generation"}}' "$worker_id" 2>/dev/null || true)"
      [ "$worker_generation" = "$CONTROL_WORKER_GENERATION" ] && continue
      worker_exec_count="$(docker inspect --format '{{len .ExecIDs}}' "$worker_id" 2>/dev/null || printf '1')"
      case "$worker_exec_count" in
        ''|*[!0-9]*) worker_exec_count=1 ;;
      esac
      if [ "$worker_exec_count" -eq 0 ]; then
        remove_bootstrap_container_exact "$worker_id"
      fi
    done

    CONTROL_WORKER_METADATA="$(docker inspect --format '{{index .Config.Labels "io.noetrium.control-worker-generation"}}|{{.State.Running}}|{{.Image}}' "$CONTROL_WORKER_NAME" 2>/dev/null || true)"
    if [ -z "$CONTROL_WORKER_METADATA" ]; then
      CONTROL_WORKER_EXTRA_ARGS="-v $WORK_ROOT:$WORK_ROOT -v $CONTROL_STATE_ROOT:$CONTROL_STATE_ROOT -v $CONTROL_RUNTIME_FABRIC_ROOT:$CONTROL_RUNTIME_FABRIC_ROOT -e NOETRIUM_CONTROL_STATE_ROOT=$CONTROL_STATE_ROOT -e NOETRIUM_RUNTIME_FABRIC_ROOT=$CONTROL_RUNTIME_FABRIC_ROOT"
      if [ -n "$CONTROL_INPUT_ROOT" ]; then
        CONTROL_WORKER_EXTRA_ARGS="$CONTROL_WORKER_EXTRA_ARGS -v $CONTROL_INPUT_ROOT:$CONTROL_INPUT_ROOT:ro -e NOETRIUM_CONTROL_INPUT_ROOT=$CONTROL_INPUT_ROOT"
      fi
      CONTROL_WORKER_ENV_ARGS=""
      if [ -n "$CONTROL_ENV_FILE" ]; then
        CONTROL_WORKER_ENV_ARGS="--env-file $CONTROL_ENV_FILE"
      fi
      # shellcheck disable=SC2086
      if ! docker run -d --init --restart unless-stopped         --tmpfs /tmp:rw,exec,nosuid,nodev,mode=1777         --name "$CONTROL_WORKER_NAME"         --label "$CONTROL_WORKER_LABEL=$CONTROL_WORKER_VALUE"         --label "$CONTROL_WORKER_PROJECT_LABEL=$CONTROL_WORKER_PROJECT_KEY"         --label "$CONTROL_WORKER_GENERATION_LABEL=$CONTROL_WORKER_GENERATION"         --entrypoint sleep         $COMMON_ARGS $CONTROL_RUNTIME_ARGS $CONTROL_WORKER_ENV_ARGS $CONTROL_WORKER_EXTRA_ARGS         "$CONTROL_IMAGE" infinity >/dev/null; then
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

    if docker exec       -e NOETRIUM_BOOTSTRAP_OWNER_PID="$$"       -e NOETRIUM_BOOTSTRAP_OWNER_BOOT="$BOOT_ID"       -e NOETRIUM_BOOTSTRAP_OWNER_START="$OWNER_START"       "$CONTROL_WORKER_NAME" python3 "$@"; then
      exit 0
    else
      exit $?
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
