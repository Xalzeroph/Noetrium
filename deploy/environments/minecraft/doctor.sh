#!/usr/bin/env bash
set -Eeuo pipefail

command -v java >/dev/null || { echo "minecraft environment requires Java" >&2; exit 2; }
command -v node >/dev/null || { echo "minecraft environment requires Node" >&2; exit 2; }
command -v npm >/dev/null || { echo "minecraft environment requires npm" >&2; exit 2; }

java_version="$(java -version 2>&1)" || {
  echo "minecraft environment Java runtime failed to execute" >&2
  exit 2
}
printf '%s\n' "${java_version%%$'\n'*}"
node --version
npm --version

bridge="${MC_BRIDGE_DIR:-/opt/noetrium-environments/minecraft/bridge}"
test -f "$bridge/package.json" || { echo "missing Mineflayer bridge package.json" >&2; exit 2; }
echo "minecraft_bridge_root=$bridge"

MC_BRIDGE_DIR="$bridge" node - <<'JS'
const fs = require('fs')
const path = require('path')
const bridge = process.env.MC_BRIDGE_DIR
function packageInfo(name) {
  const entry = require.resolve(name, { paths: [bridge] })
  let directory = path.dirname(fs.realpathSync(entry))
  while (true) {
    const manifest = path.join(directory, 'package.json')
    if (fs.existsSync(manifest)) {
      return {
        version: JSON.parse(fs.readFileSync(manifest, 'utf8')).version,
        entry,
      }
    }
    const parent = path.dirname(directory)
    if (parent === directory) {
      break
    }
    directory = parent
  }
  throw new Error('package manifest not found for ' + name + ': entry=' + entry)
}
for (const name of ['mineflayer', 'mineflayer-pathfinder', 'mineflayer-pvp', 'vec3']) {
  const info = packageInfo(name)
  console.log(name + '=' + info.version + ' entry=' + info.entry)
}
JS

data_dir="${MC_DATA_DIR:-/var/lib/minecraft}"
mkdir -p "$data_dir"
test -w "$data_dir"
echo "minecraft_data_dir=$data_dir writable=true"
