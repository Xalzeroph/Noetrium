#!/usr/bin/env bash
set -Eeuo pipefail
for command in Xvfb openbox xdotool import; do
  command -v "$command" >/dev/null || { echo "gui environment requires $command" >&2; exit 2; }
done
echo "gui_headless_stack=Xvfb,openbox,xdotool,imagemagick"
