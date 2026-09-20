#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/opt/noetrium
PACKAGE_ROOT="$(python -c 'from pathlib import Path; import noetrium_platform; print(Path(noetrium_platform.__file__).resolve().parent)')"
STATE_DIR="${PLATFORM_STATE_DIR:-/var/lib/noetrium}"

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

minecraft_doctor() {
  doctor
  command -v java >/dev/null || die "minecraft environment requires Java"
  command -v node >/dev/null || die "minecraft environment requires Node"
  command -v npm >/dev/null || die "minecraft environment requires npm"
  java -version 2>&1 | head -n 1
  node --version
  npm --version
  local bridge="${MC_BRIDGE_DIR:-$PACKAGE_ROOT/capabilities/environment/minecraft/providers/assets/mineflayer_bridge}"
  test -f "$bridge/package.json" || die "missing Mineflayer bridge package.json"
  echo "minecraft_bridge_root=$bridge"
  MC_BRIDGE_DIR="$bridge" node - <<'JS'
const fs = require('fs')
const path = require('path')
const bridge = process.env.MC_BRIDGE_DIR
function packageInfo(name) {
  const entry = require.resolve(name, { paths: [bridge] })
  let directory = path.dirname(entry)
  while (directory.startsWith(bridge) && directory !== path.dirname(bridge)) {
    const manifest = path.join(directory, 'package.json')
    if (fs.existsSync(manifest)) {
      return { version: JSON.parse(fs.readFileSync(manifest, 'utf8')).version, entry }
    }
    directory = path.dirname(directory)
  }
  throw new Error('package manifest not found for ' + name + ': entry=' + entry)
}
for (const name of ['mineflayer', 'mineflayer-pathfinder', 'mineflayer-pvp', 'vec3']) {
  const info = packageInfo(name)
  console.log(name + '=' + info.version + ' entry=' + info.entry)
}
JS
  local data_dir="${MC_DATA_DIR:-/var/lib/minecraft}"
  mkdir -p "$data_dir"
  test -w "$data_dir"
  echo "minecraft_data_dir=$data_dir writable=true"
}

embodied_doctor() {
  doctor
  python - <<'PY'
from ctypes.util import find_library
required = ("EGL", "GL", "OSMesa")
missing = [name for name in required if not find_library(name)]
if missing:
    raise SystemExit(f"missing embodied graphics libraries: {missing}")
print("embodied_graphics=EGL,GL,OSMesa")
PY
  command -v Xvfb >/dev/null || die "embodied environment requires Xvfb"
  echo "embodied_headless_display=Xvfb"
}

gui_doctor() {
  doctor
  command -v Xvfb >/dev/null || die "gui environment requires Xvfb"
  command -v openbox >/dev/null || die "gui environment requires openbox"
  command -v xdotool >/dev/null || die "gui environment requires xdotool"
  command -v import >/dev/null || die "gui environment requires ImageMagick import"
  echo "gui_headless_stack=Xvfb,openbox,xdotool,imagemagick"
}

web_doctor() {
  doctor
  command -v chromium >/dev/null || die "web environment requires Chromium"
  chromium --version
  echo "web_browser=chromium"
}

software_doctor() {
  doctor
  for command in git gcc g++ make cmake ninja patch rsync; do
    command -v "$command" >/dev/null || die "software environment requires $command"
  done
  echo "software_toolchain=git,gcc,g++,make,cmake,ninja,patch,rsync"
}

environment_doctor() {
  local profile="${1:-${NOETRIUM_ENVIRONMENT_PROFILE:-base}}"
  case "$profile" in
    base|text_world)
      doctor
      ;;
    minecraft)
      minecraft_doctor
      ;;
    embodied)
      embodied_doctor
      ;;
    gui)
      gui_doctor
      ;;
    web)
      web_doctor
      ;;
    software)
      software_doctor
      ;;
    *)
      die "unknown environment profile '$profile'"
      ;;
  esac
  echo "noetrium_environment_profile=$profile ready=true"
}

case "${1:-doctor}" in
  doctor)
    doctor
    ;;
  environment-doctor)
    shift
    environment_doctor "${1:-}"
    ;;
  minecraft-doctor)
    minecraft_doctor
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
    die "unknown command '$1' (expected doctor, environment-doctor, minecraft-doctor, verify or shell)"
    ;;
esac
