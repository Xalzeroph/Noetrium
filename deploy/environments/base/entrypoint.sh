#!/usr/bin/env bash
set -Eeuo pipefail

STATE_DIR="${PLATFORM_STATE_DIR:-/var/lib/noetrium}"
PROFILE_DOCTOR_ROOT="${NOETRIUM_ENVIRONMENT_DOCTOR_ROOT:-/usr/local/lib/noetrium/environment-doctor.d}"

base_doctor() {
  python --version
  mkdir -p "$STATE_DIR"
  test -w "$STATE_DIR"
  echo "environment_state_dir=$STATE_DIR writable=true"
}

environment_doctor() {
  local profile="${1:-${NOETRIUM_ENVIRONMENT_PROFILE:-base}}"
  base_doctor
  case "$profile" in
    base|text_world) ;;
    *)
      local hook="$PROFILE_DOCTOR_ROOT/$profile"
      test -x "$hook" || {
        echo "environment profile '$profile' has no executable doctor hook: $hook" >&2
        exit 2
      }
      "$hook"
      ;;
  esac
  echo "noetrium_environment_profile=$profile ready=true"
}

case "${1:-environment-doctor}" in
  environment-doctor)
    shift
    environment_doctor "${1:-}"
    ;;
  doctor)
    base_doctor
    ;;
  shell)
    shift
    if [[ $# -eq 0 ]]; then exec /bin/sh; fi
    exec "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
