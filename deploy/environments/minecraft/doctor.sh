#!/usr/bin/env bash
set -Eeuo pipefail
command -v java >/dev/null || { echo "minecraft environment requires Java" >&2; exit 2; }
command -v node >/dev/null || { echo "minecraft environment requires Node" >&2; exit 2; }
command -v npm >/dev/null || { echo "minecraft environment requires npm" >&2; exit 2; }
java -version 2>&1 | head -n 1
node --version
npm --version
PACKAGE_ROOT="$(python -c 'from pathlib import Path; import noetrium_platform; print(Path(noetrium_platform.__file__).resolve().parent)')"
bridge="${MC_BRIDGE_DIR:-$PACKAGE_ROOT/capabilities/environment/minecraft/providers/assets/mineflayer_bridge}"
test -f "$bridge/package.json" || { echo "missing Mineflayer bridge package.json" >&2; exit 2; }
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
data_dir="${MC_DATA_DIR:-/var/lib/minecraft}"
mkdir -p "$data_dir"
test -w "$data_dir"
echo "minecraft_data_dir=$data_dir writable=true"
