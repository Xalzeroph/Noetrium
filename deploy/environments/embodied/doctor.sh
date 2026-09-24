#!/usr/bin/env bash
set -Eeuo pipefail
python - <<'PY'
from ctypes.util import find_library
required = ("EGL", "GL", "OSMesa")
missing = [name for name in required if not find_library(name)]
if missing:
    raise SystemExit(f"missing embodied graphics libraries: {missing}")
print("embodied_graphics=EGL,GL,OSMesa")
PY
command -v Xvfb >/dev/null || { echo "embodied environment requires Xvfb" >&2; exit 2; }
echo "embodied_headless_display=Xvfb"
