#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
STATE_ROOT="${NOETRIUM_DEPLOYMENT_STATE_ROOT:-$ROOT/.noetrium/deployment}"
DATA_ROOT="${NOETRIUM_DOCKER_DATA_ROOT:-$STATE_ROOT/docker}"
RUNTIME_ROOT="${NOETRIUM_DOCKER_RUNTIME_ROOT:-$STATE_ROOT/docker-runtime}"
XDG_ROOT="${NOETRIUM_DOCKER_XDG_RUNTIME_DIR:-$RUNTIME_ROOT/xdg}"
SOCKET="${NOETRIUM_DOCKER_SOCKET:-$RUNTIME_ROOT/docker.sock}"
PID_FILE="$RUNTIME_ROOT/dockerd-rootless.pid"
LOG_FILE="$RUNTIME_ROOT/dockerd-rootless.log"

die() { echo "noetrium-rootless-docker: $*" >&2; exit 2; }
require_command() { command -v "$1" >/dev/null 2>&1 || die "missing rootless prerequisite: $1"; }
subid_present() {
  file="$1"; user="$2"
  awk -F: -v user="$user" '$1 == user && $2 ~ /^[0-9]+$/ && $3 ~ /^[0-9]+$/ && $3 >= 65536 { found=1 } END { exit(found ? 0 : 1) }' "$file"
}
check_prerequisites() {
  require_command docker
  require_command dockerd-rootless.sh
  require_command rootlesskit
  require_command slirp4netns
  require_command newuidmap
  require_command newgidmap
  user="$(id -un)"
  subid_present /etc/subuid "$user" || die "user $user requires at least 65536 subordinate UIDs in /etc/subuid"
  subid_present /etc/subgid "$user" || die "user $user requires at least 65536 subordinate GIDs in /etc/subgid"
  if [ -r /proc/sys/kernel/unprivileged_userns_clone ]; then
    [ "$(cat /proc/sys/kernel/unprivileged_userns_clone)" = "1" ] || die "kernel.unprivileged_userns_clone must be 1"
  fi
  if [ -r /proc/sys/user/max_user_namespaces ]; then
    max_userns="$(cat /proc/sys/user/max_user_namespaces)"
    [ "$max_userns" -gt 0 ] 2>/dev/null || die "user namespaces are disabled"
  fi
  mkdir -p "$DATA_ROOT" "$RUNTIME_ROOT" "$XDG_ROOT"
  chmod 700 "$XDG_ROOT"
  [ -w "$DATA_ROOT" ] || die "Docker data root is not writable: $DATA_ROOT"
  [ -w "$RUNTIME_ROOT" ] || die "Docker runtime root is not writable: $RUNTIME_ROOT"
  [ -w "$XDG_ROOT" ] || die "XDG runtime root is not writable: $XDG_ROOT"
  echo "rootless_prerequisites_ready=true"
  echo "rootless_data_root=$DATA_ROOT"
  echo "rootless_runtime_root=$RUNTIME_ROOT"
  echo "rootless_socket=$SOCKET"
}
daemon_ready() { DOCKER_HOST="unix://$SOCKET" docker info >/dev/null 2>&1; }
daemon_root() { DOCKER_HOST="unix://$SOCKET" docker info --format '{{.DockerRootDir}}'; }
require_expected_root() {
  actual="$(daemon_root)"
  expected="$(CDPATH= cd -- "$DATA_ROOT" && pwd -P)"
  actual_parent="$(dirname "$actual")"; actual_name="$(basename "$actual")"
  if [ -d "$actual_parent" ]; then actual="$(CDPATH= cd -- "$actual_parent" && pwd -P)/$actual_name"; fi
  [ "$actual" = "$expected" ] || die "rootless DockerRootDir drifted: expected=$expected actual=$actual"
}
status_daemon() {
  if daemon_ready; then
    require_expected_root
    echo "rootless_docker_ready=true"
    echo "DOCKER_HOST=unix://$SOCKET"
    echo "DockerRootDir=$(daemon_root)"
    return 0
  fi
  echo "rootless_docker_ready=false"
  [ ! -f "$PID_FILE" ] || echo "pid_file=$(cat "$PID_FILE" 2>/dev/null || true)"
  return 1
}
start_daemon() {
  check_prerequisites
  if daemon_ready; then require_expected_root; status_daemon; return 0; fi
  if [ -f "$PID_FILE" ]; then
    stale="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$stale" ] && kill -0 "$stale" 2>/dev/null; then die "rootless Docker process exists but daemon is not ready: pid=$stale"; fi
    rm -f "$PID_FILE"
  fi
  mkdir -p "$DATA_ROOT" "$RUNTIME_ROOT" "$XDG_ROOT"; chmod 700 "$XDG_ROOT"; rm -f "$SOCKET"
  (
    export XDG_RUNTIME_DIR="$XDG_ROOT"
    export DOCKERD_ROOTLESS_ROOTLESSKIT_NET="${DOCKERD_ROOTLESS_ROOTLESSKIT_NET:-slirp4netns}"
    exec dockerd-rootless.sh --data-root "$DATA_ROOT" --exec-root "$RUNTIME_ROOT/exec" --host "unix://$SOCKET"
  ) >"$LOG_FILE" 2>&1 &
  pid=$!; printf '%s\n' "$pid" >"$PID_FILE"
  attempts=0
  while [ "$attempts" -lt 60 ]; do
    if daemon_ready; then require_expected_root; status_daemon; return 0; fi
    if ! kill -0 "$pid" 2>/dev/null; then tail -n 80 "$LOG_FILE" >&2 || true; die "rootless Docker exited during startup"; fi
    attempts=$((attempts + 1)); sleep 1
  done
  tail -n 80 "$LOG_FILE" >&2 || true
  die "rootless Docker did not become ready within 60 seconds"
}
stop_daemon() {
  if [ ! -f "$PID_FILE" ]; then
    if daemon_ready; then die "rootless Docker is reachable but owner PID file is missing; refusing ambiguous stop"; fi
    rm -f "$SOCKET"; echo "rootless_docker_stopped=true"; return 0
  fi
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"; [ -n "$pid" ] || die "rootless Docker PID file is empty"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"; attempts=0
    while kill -0 "$pid" 2>/dev/null && [ "$attempts" -lt 30 ]; do attempts=$((attempts + 1)); sleep 1; done
    kill -0 "$pid" 2>/dev/null && die "rootless Docker process did not stop: pid=$pid"
  fi
  if daemon_ready; then die "rootless Docker socket remains live after owner process stopped"; fi
  rm -f "$PID_FILE" "$SOCKET"; echo "rootless_docker_stopped=true"
}
print_env() {
  printf 'export DOCKER_HOST=%s\n' "unix://$SOCKET"
  printf 'export NOETRIUM_DOCKER_DATA_ROOT=%s\n' "$DATA_ROOT"
}
case "${1:-}" in
  doctor) check_prerequisites ;;
  start) start_daemon ;;
  status) status_daemon ;;
  stop) stop_daemon ;;
  env) print_env ;;
  *) echo "Usage: ./deploy/rootless-docker.sh <doctor|start|status|stop|env>" >&2; exit 2 ;;
esac
