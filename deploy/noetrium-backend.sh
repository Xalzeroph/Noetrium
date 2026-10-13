#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PATH_HELPERS="$ROOT/deploy/noetrium-paths.sh"
. "$PATH_HELPERS"
ENV_BOOTSTRAP="$ROOT/deploy/build-environments.sh"
ROOTLESS_DOCKER="$ROOT/deploy/rootless-docker.sh"
DATA_ROOT="${NOETRIUM_DATA_ROOT:-$ROOT/.noetrium}"
MACHINE_STATE_ROOT="$(noetrium_machine_state_root "$ROOT")"
STATE_ROOT="${NOETRIUM_DEPLOYMENT_STATE_ROOT:-$DATA_ROOT/deployment}"
ENV_WORK_ROOT="${NOETRIUM_BUILD_WORK_ROOT:-$MACHINE_STATE_ROOT/environment-images}"
FLEET_STATE_ROOT="$STATE_ROOT/reproduction-fleet"
PROJECTS_STATE_ROOT="$DATA_ROOT/projects"
RUNTIME_FABRIC_ROOT="${NOETRIUM_RUNTIME_FABRIC_ROOT:-$MACHINE_STATE_ROOT/runtime-fabric}"
RUNTIME_CACHE_ROOT="${NOETRIUM_RUNTIME_CACHE_ROOT:-$MACHINE_STATE_ROOT/runtime-cache}"

die() {
  echo "noetrium-deploy: $*" >&2
  exit 2
}

finalization_audit() {
  python_bin="${NOETRIUM_PYTHON:-$ROOT/.venv/bin/python}"
  [ -x "$python_bin" ] || die "finalization audit requires executable Python: $python_bin"
  PYTHONDONTWRITEBYTECODE=1 "$python_bin" "$ROOT/scripts/finalization_audit.py" "$@"
}

host_doctor() {
  command -v docker >/dev/null 2>&1 || die "Docker CLI is required on the host"
  NOETRIUM_DOCKER_DAEMON_CAPABILITY_IDENTITY="$(
    docker info --format '{{.ID}}|{{.ServerVersion}}|{{.Driver}}|{{.DefaultRuntime}}|{{json .Runtimes}}|{{json .CDISpecDirs}}' 2>/dev/null
  )" || die "ordinary user cannot reach the active Docker daemon"
  [ -n "$NOETRIUM_DOCKER_DAEMON_CAPABILITY_IDENTITY" ] || die "Docker daemon did not publish a stable capability identity"
  export NOETRIUM_DOCKER_DAEMON_CAPABILITY_IDENTITY
  export NOETRIUM_DOCKER_CAPABILITY_VERIFIED=1
  mkdir -p "$DATA_ROOT" "$ENV_WORK_ROOT" "$FLEET_STATE_ROOT" "$PROJECTS_STATE_ROOT" "$RUNTIME_FABRIC_ROOT"

  if [ -n "${NOETRIUM_DOCKER_DATA_ROOT:-}" ]; then
    mkdir -p "$NOETRIUM_DOCKER_DATA_ROOT"
    expected="$(CDPATH= cd -- "$NOETRIUM_DOCKER_DATA_ROOT" && pwd -P)"
    actual="$(docker info --format '{{.DockerRootDir}}')"
    actual_parent="$(dirname "$actual")"
    actual_name="$(basename "$actual")"
    if [ -d "$actual_parent" ]; then
      actual="$(CDPATH= cd -- "$actual_parent" && pwd -P)/$actual_name"
    fi
    [ "$actual" = "$expected" ] || die "active DockerRootDir does not match NOETRIUM_DOCKER_DATA_ROOT: expected=$expected actual=$actual"
  fi
}

authority_materializer_from_env_file() {
  file="${NOETRIUM_CONTROL_ENV_FILE:-$ROOT/deploy/.env}"
  [ -f "$file" ] || return 0
  sed -n 's/^NOETRIUM_FLEET_AUTHORITY_MATERIALIZER=//p' "$file" | tail -n 1
}

control_input_root_from_env_file() {
  file="${NOETRIUM_CONTROL_ENV_FILE:-$ROOT/deploy/.env}"
  [ -f "$file" ] || return 0
  sed -n "s/^NOETRIUM_CONTROL_INPUT_ROOT=//p" "$file" | tail -n 1
}

authority_materializer() {
  if [ -n "${NOETRIUM_FLEET_AUTHORITY_MATERIALIZER:-}" ]; then
    printf '%s\n' "$NOETRIUM_FLEET_AUTHORITY_MATERIALIZER"
    return 0
  fi
  authority_materializer_from_env_file
}

authority_requirements_path() {
  printf '%s\n' "$FLEET_STATE_ROOT/authority-prerequisites.json"
}

emit_authority_requirements() {
  path="$(authority_requirements_path)"
  mkdir -p "$FLEET_STATE_ROOT"
  fleet --requirements --output "$path"
  printf 'noetrium_authority_requirements=%s\n' "$path"
}


fleet_with_optional_materializer() {
  materializer="$(authority_materializer)"
  if [ -n "$materializer" ]; then
    fleet "$@" --authority-materializer "$materializer"
  else
    fleet "$@"
  fi
}

environment_bootstrap() {
  NOETRIUM_BUILD_WORK_ROOT="$ENV_WORK_ROOT" "$ENV_BOOTSTRAP" "$@"
}

control_python() {
  input_root="${NOETRIUM_CONTROL_INPUT_ROOT:-}"
  if [ -z "$input_root" ]; then
    input_root="$(control_input_root_from_env_file)"
  fi
  if [ -n "$input_root" ]; then
    export NOETRIUM_CONTROL_INPUT_ROOT="$input_root"
  fi
  NOETRIUM_BUILD_WORK_ROOT="$ENV_WORK_ROOT" \
    NOETRIUM_CONTROL_STATE_ROOT="$FLEET_STATE_ROOT" \
    NOETRIUM_RUNTIME_FABRIC_ROOT="$RUNTIME_FABRIC_ROOT" \
    NOETRIUM_RUNTIME_CACHE_ROOT="$RUNTIME_CACHE_ROOT" \
    "$ENV_BOOTSTRAP" control "$@"
}

fleet() {
  control_python scripts/run_reproduction_fleet.py "$@"
}

has_explicit_projects() {
  for argument in "$@"; do
    case "$argument" in
      --project|--project=*)
        return 0
        ;;
    esac
  done
  return 1
}

root_set_file_from_args() {
  # Fast execution control runs before host_doctor. A brand-new data root must
  # create its projects directory before the temporary root-set file, otherwise
  # every first invocation pays a failed fast path plus full fallback bootstrap.
  mkdir -p "$PROJECTS_STATE_ROOT" || return 125
  tmp="$PROJECTS_STATE_ROOT/.root-set.$$"
  : > "$tmp"
  expect_root=0
  for argument in "$@"; do
    if [ "$expect_root" = "1" ]; then
      root="$argument"
      expect_root=0
      test -d "$root" || die "project root does not exist: $root"
      test ! -L "$root" || die "project root must not be a symlink: $root"
      root="$(CDPATH= cd -- "$root" && pwd -P)"
      printf '%s\n' "$root" >> "$tmp"
      continue
    fi
    case "$argument" in
      --project) expect_root=1 ;;
      --project=*)
        root="${argument#--project=}"
        test -d "$root" || die "project root does not exist: $root"
        test ! -L "$root" || die "project root must not be a symlink: $root"
        root="$(CDPATH= cd -- "$root" && pwd -P)"
        printf '%s\n' "$root" >> "$tmp"
        ;;
    esac
  done
  [ "$expect_root" = "0" ] || die "--project requires a path"
  [ -s "$tmp" ] || { rm -f "$tmp"; die "at least one --project is required"; }
  lines="$(wc -l < "$tmp" | tr -d ' ')"
  unique="$(sort -u "$tmp" | wc -l | tr -d ' ')"
  [ "$lines" = "$unique" ] || { rm -f "$tmp"; die "project roots must be unique"; }
  sorted="$tmp.sorted"
  sort "$tmp" > "$sorted"
  rm -f "$tmp"
  digest="$(sha256sum "$sorted" | awk '{print $1}')"
  root_set_dir="$PROJECTS_STATE_ROOT/root-sets/$digest"
  mkdir -p "$root_set_dir"
  target="$root_set_dir/roots.txt"
  if [ -f "$target" ]; then
    cmp -s "$sorted" "$target" || { rm -f "$sorted"; die "root-set digest collision"; }
    rm -f "$sorted"
  else
    mv "$sorted" "$target"
  fi
  printf '%s\n' "$target"
}

root_set_fast_execution_control() {
  action="$1"
  shift
  command -v docker >/dev/null 2>&1 || return 125
  roots_file="$(root_set_file_with_default "$@")" || return 125
  root_set_dir="$(dirname "$roots_file")"
  record="$root_set_dir/control-worker.fast"
  [ -f "$record" ] && [ ! -L "$record" ] || return 125
  {
    IFS= read -r worker_name || return 125
    IFS= read -r worker_generation || return 125
    IFS= read -r worker_image || return 125
  } < "$record"
  case "$worker_name" in
    noetrium-control-*) ;;
    *) return 125 ;;
  esac
  case "$worker_generation" in
    ????????????????????????????????????????????????????????????????) ;;
    *) return 125 ;;
  esac
  case "$worker_image" in
    sha256:????????????????????????????????????????????????????????????????) ;;
    *) return 125 ;;
  esac
  expected_control_env_digest="none"
  control_env_file="${NOETRIUM_CONTROL_ENV_FILE:-}"
  if [ -n "$control_env_file" ]; then
    [ -f "$control_env_file" ] && [ ! -L "$control_env_file" ] || return 125
    expected_control_env_digest="$(sha256sum "$control_env_file" 2>/dev/null | awk '{print $1}')" || return 125
    [ -n "$expected_control_env_digest" ] || return 125
  fi
  worker_metadata="$(
    docker inspect --format '{{index .Config.Labels "io.noetrium.control-worker-generation"}}|{{index .Config.Labels "io.noetrium.control-worker-env-digest"}}|{{.State.Running}}|{{.Image}}' "$worker_name" 2>/dev/null
  )" || return 125
  worker_actual_generation="${worker_metadata%%|*}"
  worker_rest="${worker_metadata#*|}"
  worker_actual_env_digest="${worker_rest%%|*}"
  worker_rest="${worker_rest#*|}"
  worker_running="${worker_rest%%|*}"
  worker_actual_image="${worker_rest#*|}"
  [ "$worker_actual_generation" = "$worker_generation" ] || return 125
  [ "$worker_actual_env_digest" = "$expected_control_env_digest" ] || return 125
  [ "$worker_running" = "true" ] || return 125
  [ "$worker_actual_image" = "$worker_image" ] || return 125

  case "$action" in
    preflight) mode="--preflight" ;;
    run) mode="--execute" ;;
    *) return 125 ;;
  esac
  fast_boot_id=""
  IFS= read -r fast_boot_id < /proc/sys/kernel/random/boot_id || return 125
  fast_stat=""
  IFS= read -r fast_stat < "/proc/$$/stat" || return 125
  set -- $fast_stat
  [ "$#" -ge 22 ] || return 125
  fast_owner_start="${22}"
  request_lease_dir="$root_set_dir/control-request-leases"
  mkdir -p "$request_lease_dir" || return 125
  request_lease="$request_lease_dir/$fast_boot_id.$$.$fast_owner_start.lock"
  exec 8>"$request_lease" || return 125
  flock -x 8 || { exec 8>&-; return 125; }
  if docker exec \
    -e NOETRIUM_BOOTSTRAP_OWNER_PID="$$" \
    -e NOETRIUM_BOOTSTRAP_OWNER_BOOT="$fast_boot_id" \
    -e NOETRIUM_BOOTSTRAP_OWNER_START="$fast_owner_start" \
    -e NOETRIUM_CONTROL_REQUEST_LEASE="$request_lease" \
    "$worker_name" \
    python3 "$ROOT/scripts/control_worker.py" \
      --socket /tmp/noetrium-control.sock request -- \
      "$ROOT/scripts/run_research_roots.py" \
      --project-roots-file "$roots_file" \
      --state-root "$root_set_dir" \
      --work-root "$ENV_WORK_ROOT" \
      "$mode" 8>&-; then
    request_status=0
  else
    request_status=$?
  fi
  flock -u 8
  exec 8>&-
  rm -f "$request_lease"
  return "$request_status"
}

root_set_execution_control() {
  action="$1"
  shift
  roots_file="$(root_set_file_with_default "$@")"
  root_set_dir="$(dirname "$roots_file")"
  mkdir -p "$root_set_dir"

  case "$action" in
    preflight) mode="--preflight" ;;
    run) mode="--execute" ;;
    *) die "unsupported root-set execution action: $action" ;;
  esac

  NOETRIUM_CONTROL_PROJECT_ROOTS_FILE="$roots_file" \
  NOETRIUM_CONTROL_HOST_RUNTIME=1 \
  NOETRIUM_CONTROL_STATE_ROOT="$root_set_dir" \
  NOETRIUM_RUNTIME_FABRIC_ROOT="$RUNTIME_FABRIC_ROOT" \
  NOETRIUM_RUNTIME_CACHE_ROOT="$RUNTIME_CACHE_ROOT" \
  NOETRIUM_BUILD_WORK_ROOT="$ENV_WORK_ROOT" \
    "$ENV_BOOTSTRAP" control \
      "$ROOT/scripts/run_research_roots.py" \
      --project-roots-file "$roots_file" \
      --state-root "$root_set_dir" \
      --work-root "$ENV_WORK_ROOT" \
      "$mode"
}

root_set_file_with_default() {
  if has_explicit_projects "$@"; then
    root_set_file_from_args "$@"
  else
    root_set_file_from_args --project .
  fi
}

root_set_lifecycle_control() {
  action="$1"
  shift
  roots_file="$(root_set_file_with_default "$@")"
  root_set_dir="$(dirname "$roots_file")"
  mkdir -p "$root_set_dir"

  NOETRIUM_CONTROL_PROJECT_ROOTS_FILE="$roots_file" \
  NOETRIUM_CONTROL_HOST_RUNTIME=1 \
  NOETRIUM_CONTROL_STATE_ROOT="$root_set_dir" \
  NOETRIUM_RUNTIME_FABRIC_ROOT="$RUNTIME_FABRIC_ROOT" \
  NOETRIUM_RUNTIME_CACHE_ROOT="$RUNTIME_CACHE_ROOT" \
  NOETRIUM_BUILD_WORK_ROOT="$ENV_WORK_ROOT" \
    "$ENV_BOOTSTRAP" control \
      -c 'from noetrium_platform.composition.operator.wiring.research import main; import sys; raise SystemExit(main(sys.argv[1:]))' \
      "$action" "$@"
}

project_file_control() {
  [ "$#" -gt 0 ] || die "project requires create|sync|doctor|test"
  action="$1"
  shift
  case "$action" in
    sync|doctor|test)
      roots_file="$(root_set_file_with_default "$@")"
      lines="$(wc -l < "$roots_file" | tr -d ' ')"
      [ "$lines" = "1" ] || die "project $action operates on exactly one project root"
      root_set_dir="$(dirname "$roots_file")"
      NOETRIUM_CONTROL_PROJECT_ROOTS_FILE="$roots_file" \
      NOETRIUM_CONTROL_HOST_RUNTIME=1 \
      NOETRIUM_CONTROL_STATE_ROOT="$root_set_dir" \
      NOETRIUM_RUNTIME_FABRIC_ROOT="$RUNTIME_FABRIC_ROOT" \
      NOETRIUM_RUNTIME_CACHE_ROOT="$RUNTIME_CACHE_ROOT" \
      NOETRIUM_BUILD_WORK_ROOT="$ENV_WORK_ROOT" \
        "$ENV_BOOTSTRAP" control \
          -c 'from noetrium_platform.composition.operator.wiring.research import main; import sys; raise SystemExit(main(sys.argv[1:]))' \
          project "$action" "$@"
      ;;
    create)
      control_python -c 'from noetrium_platform.composition.operator.wiring.research import main; import sys; raise SystemExit(main(sys.argv[1:]))' project create "$@"
      ;;
    *) die "unsupported project file action: $action" ;;
  esac
}


command="${1:-}"
[ -n "$command" ] || {
  die "internal backend requires an action"
}
shift

case "$command" in
  audit-finalization)
    finalization_audit "$@"
    ;;
  doctor)
    host_doctor
    environment_bootstrap validate
    echo "noetrium_deployment_ready=true"
    ;;
  build)
    host_doctor
    environment_bootstrap build "$@"
    ;;
  plan)
    host_doctor
    fleet "$@" --state-root "$FLEET_STATE_ROOT"
    ;;
  requirements)
    host_doctor
    emit_authority_requirements
    ;;
  preflight)
    if root_set_fast_execution_control preflight "$@"; then
      exit 0
    else
      fast_status=$?
    fi
    case "$fast_status" in
      74|75|125) ;;
      *) exit "$fast_status" ;;
    esac
    host_doctor
    root_set_execution_control preflight "$@"
    ;;
  run)
    if root_set_fast_execution_control run "$@"; then
      exit 0
    else
      fast_status=$?
    fi
    case "$fast_status" in
      74|75|125) ;;
      *) exit "$fast_status" ;;
    esac
    host_doctor
    root_set_execution_control run "$@"
    ;;
  inspect|pause|drain|interrupt|resume|retry|cancel|checkpoint|reconcile|migrate|retire)
    host_doctor
    root_set_lifecycle_control "$command" "$@"
    ;;
  project)
    host_doctor
    if [ "${1:-}" = "run" ]; then
      die "project run was removed; use ./deploy/noetrium run --project <path>"
    fi
    project_file_control "$@"
    ;;
  env)
    host_doctor
    environment_bootstrap "$@"
    ;;
  docker)
    [ "$#" -gt 0 ] || die "docker requires doctor|start|status|stop|env"
    "$ROOTLESS_DOCKER" "$@"
    ;;
  *)
    die "unknown internal action: $command"
    ;;
esac
