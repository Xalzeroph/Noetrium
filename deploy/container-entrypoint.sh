#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/opt/noetrium
STATE_DIR="${PLATFORM_STATE_DIR:-/var/lib/noetrium}"
PROFILE_DOCTOR_ROOT="${NOETRIUM_ENVIRONMENT_DOCTOR_ROOT:-/usr/local/lib/noetrium/environment-doctor.d}"

die() {
  echo "container-entrypoint: $*" >&2
  exit 2
}

doctor() {
  python --version
  python - <<'PY'
from importlib.metadata import version
import noetrium_platform

print(f"noetrium_platform_import={noetrium_platform.__name__}")
print(f"noetrium_platform_version={version('noetrium')}")
PY
  noetrium --help >/dev/null
  noetrium-manage --help >/dev/null
  noetrium-architecture-gate --help >/dev/null 2>&1 || true
  mkdir -p "$STATE_DIR"
  test -w "$STATE_DIR"
  echo "platform_state_dir=$STATE_DIR writable=true"
}

environment_doctor() {
  local profile="${1:-${NOETRIUM_ENVIRONMENT_PROFILE:-base}}"
  doctor

  case "$profile" in
    base|text_world)
      ;;
    *)
      local hook="$PROFILE_DOCTOR_ROOT/$profile"
      test -x "$hook" || die "environment profile '$profile' has no executable doctor hook: $hook"
      "$hook"
      ;;
  esac

  echo "noetrium_environment_profile=$profile ready=true"
  if [ -n "${NOETRIUM_ENVIRONMENT_PROFILE_REVISION:-}" ]; then
    echo "noetrium_environment_profile_revision=$NOETRIUM_ENVIRONMENT_PROFILE_REVISION"
  fi
  if [ -n "${NOETRIUM_ENVIRONMENT_INSTANCE_ID:-}" ]; then
    echo "noetrium_environment_instance_id=$NOETRIUM_ENVIRONMENT_INSTANCE_ID"
  fi
}

case "${1:-doctor}" in
  doctor)
    doctor
    ;;
  environment-doctor)
    shift
    environment_doctor "${1:-}"
    ;;
  verify)
    doctor
    exec noetrium-architecture-gate
    ;;
  shell)
    shift
    if [[ $# -eq 0 ]]; then
      exec /bin/sh
    fi
    exec "$@"
    ;;
  *)
    die "unknown command '$1' (expected doctor, environment-doctor, verify or shell)"
    ;;
esac
