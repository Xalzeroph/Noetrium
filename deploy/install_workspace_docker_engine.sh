#!/usr/bin/env bash
set -Eeuo pipefail

# Installs a self-contained Docker client/daemon and Compose plugin under the
# repository. It never writes /usr, /var/lib/docker or a system service.
# Concurrency-Policy: DETACHED_DAEMON
# Concurrency-Rationale: dockerd intentionally outlives this launcher and is owned by its pidfile, Unix socket readiness probe, status command, data root, and log file.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE_DIR="${ROOT}/.docker-engine"
ENGINE_VERSION="${DOCKER_ENGINE_VERSION:-28.3.3}"
COMPOSE_VERSION="${DOCKER_COMPOSE_VERSION:-v2.39.2}"
BUILDX_VERSION="${DOCKER_BUILDX_VERSION:-v0.26.1}"
ARCH="$(uname -m)"
[[ "$ARCH" == "x86_64" ]] || { echo "unsupported architecture: $ARCH" >&2; exit 2; }

case "$(uname -r)" in
  *microsoft*|*Microsoft*|*WSL*)
    RUNTIME_DIR="${WSL_DOCKER_RUNTIME_DIR:-/tmp/noetrium-docker}"
    DATA_DIR="${WSL_DOCKER_DATA_ROOT:-/tmp/noetrium-docker-data}"
    ;;
  *)
    RUNTIME_DIR="$ENGINE_DIR/run"
    DATA_DIR="$ENGINE_DIR/data"
    ;;
esac
SOCKET="$RUNTIME_DIR/docker.sock"
PIDFILE="$RUNTIME_DIR/dockerd.pid"
LOGFILE="$RUNTIME_DIR/dockerd.log"

install_engine() {
  mkdir -p "$ENGINE_DIR/download/extract" "$ENGINE_DIR/bin" "$ENGINE_DIR/config/cli-plugins" "$DATA_DIR" "$RUNTIME_DIR" "$RUNTIME_DIR/exec"
  cd "$ENGINE_DIR/download"
  if [[ ! -s "docker-${ENGINE_VERSION}.tgz" ]]; then
    curl -fL --retry 3 --connect-timeout 15 -o "docker-${ENGINE_VERSION}.tgz" "https://download.docker.com/linux/static/stable/x86_64/docker-${ENGINE_VERSION}.tgz"
  fi
  tar --no-same-owner --no-same-permissions --overwrite -xzf "docker-${ENGINE_VERSION}.tgz" -C extract
  cp -a extract/docker/. "$ENGINE_DIR/bin/"
  chmod +x "$ENGINE_DIR/bin"/*
  if [[ ! -s "$ENGINE_DIR/config/cli-plugins/docker-compose" ]]; then
    curl -fL --retry 3 --connect-timeout 15 -o "$ENGINE_DIR/config/cli-plugins/docker-compose" "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64"
  fi
  if [[ ! -s "$ENGINE_DIR/config/cli-plugins/docker-buildx" ]]; then
    curl -fL --retry 3 --connect-timeout 15 -o "$ENGINE_DIR/config/cli-plugins/docker-buildx" "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-amd64"
  fi
  chmod +x "$ENGINE_DIR/config/cli-plugins/docker-compose" "$ENGINE_DIR/config/cli-plugins/docker-buildx"
  echo "Docker client: $($ENGINE_DIR/bin/docker --version)"
  echo "Compose: $(DOCKER_CONFIG="$ENGINE_DIR/config" "$ENGINE_DIR/bin/docker" compose version)"
  echo "Buildx: $(DOCKER_CONFIG="$ENGINE_DIR/config" "$ENGINE_DIR/bin/docker" buildx version)"
  echo "Installed under $ENGINE_DIR; runtime data: $DATA_DIR; socket: $SOCKET"
}

start_engine() {
  [[ "$(id -u)" == "0" ]] || { echo "workspace Engine start requires rootful Linux privileges; use Docker Desktop/WSL2 or a system daemon" >&2; exit 2; }
  if [[ -f "$PIDFILE" ]] && kill -0 "$(<"$PIDFILE")" 2>/dev/null; then
    echo "dockerd already running: pid=$(<"$PIDFILE")"; return 0
  fi
  if [[ -e "$SOCKET" ]]; then echo "refusing to reuse stale Docker socket: $SOCKET" >&2; exit 2; fi
  PATH="$ENGINE_DIR/bin:$PATH" nohup "$ENGINE_DIR/bin/dockerd" \
    --host="unix://$SOCKET" --data-root="$DATA_DIR" --exec-root="$RUNTIME_DIR/exec" --pidfile="$PIDFILE" \
    --storage-driver=vfs --bridge=none --iptables=false --ip6tables=false --ip-forward=false --ip-masq=false \
    --userland-proxy=false --log-level=info >"$LOGFILE" 2>&1 &
  for _ in $(seq 1 40); do
    if [[ -S "$SOCKET" ]] && DOCKER_HOST="unix://$SOCKET" DOCKER_CONFIG="$ENGINE_DIR/config" "$ENGINE_DIR/bin/docker" info >/dev/null 2>&1; then
      echo "Docker daemon ready: DOCKER_HOST=unix://$SOCKET"; return 0
    fi
    sleep 1
  done
  echo "Docker daemon did not become ready; log: $LOGFILE" >&2
  tail -120 "$LOGFILE" >&2 || true
  exit 1
}

status_engine() {
  if [[ -f "$PIDFILE" ]] && kill -0 "$(<"$PIDFILE")" 2>/dev/null; then
    DOCKER_HOST="unix://$SOCKET" DOCKER_CONFIG="$ENGINE_DIR/config" "$ENGINE_DIR/bin/docker" info --format 'Server={{.ServerVersion}} Driver={{.Driver}}'
  else echo "Docker daemon is not running"; return 1; fi
}

case "${1:-install}" in
  install) install_engine ;;
  start) install_engine; start_engine ;;
  status) status_engine ;;
  *) echo "usage: $0 [install|start|status]" >&2; exit 2 ;;
esac
