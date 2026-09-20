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

test -S /var/run/docker.sock || {
  echo "Docker socket /var/run/docker.sock is unavailable." >&2
  exit 1
}

mkdir -p "$WORK_ROOT"
WORK_ROOT="$(CDPATH= cd -- "$WORK_ROOT" && pwd)"

docker build \
  --build-arg "DOCKER_CLI_IMAGE=$DOCKER_CLI_IMAGE" \
  --tag "$BOOTSTRAP_IMAGE" \
  --file "$ROOT/deploy/bootstrap/Dockerfile" \
  "$ROOT"

# The bootstrap talks to the host Docker daemon. Preserve host absolute paths
# inside the control-plane container so daemon-side build contexts and Compose
# bind mounts resolve to the same files. Source stays read-only; only the
# dedicated build/runtime root is writable.
COMMON_ARGS="-v /var/run/docker.sock:/var/run/docker.sock -v $ROOT:$ROOT:ro -w $ROOT"

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
