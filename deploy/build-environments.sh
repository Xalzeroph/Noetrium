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

docker build \
  --build-arg "DOCKER_CLI_IMAGE=$DOCKER_CLI_IMAGE" \
  --tag "$BOOTSTRAP_IMAGE" \
  --file "$ROOT/deploy/bootstrap/Dockerfile" \
  "$ROOT"

# Git metadata is mounted read-only because exact source identity and a clean
# checkout are scientific provenance inputs. Source is mounted read-only; only
# the dedicated build/runtime root is writable.
if [ "${1:-}" = "build" ]; then
  exec docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$ROOT:/workspace:ro" \
    -v "$WORK_ROOT:/work" \
    -w /workspace \
    "$BOOTSTRAP_IMAGE" \
    "$@" \
    --work-root /work \
    --output /work/environment-image-build.json
fi

exec docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$ROOT:/workspace:ro" \
  -w /workspace \
  "$BOOTSTRAP_IMAGE" \
  "$@"
